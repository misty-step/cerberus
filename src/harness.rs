use std::collections::BTreeMap;
use std::fs;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use anyhow::{anyhow, Context, Result};
use clap::ValueEnum;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

use crate::digest::{request_digest, sha256_digest};
use crate::prompt::{build_master_prompt, build_opencode_message};
use crate::schema::{
    ContextArtifact, ContextCapabilities, LifecycleState, ReceiptStatus, ReviewArtifact,
    ReviewRequest, ReviewTelemetry, RuntimeTarget,
};
use crate::telemetry::{omp_telemetry, opencode_telemetry};
use crate::validation::validate_artifact_for_request;

/// Filename the review agent writes its `ReviewArtifact.v1` JSON to, inside the
/// disposable review workspace (`--dir`). The harness reads it back and parses
/// it; there is no transcript scraping.
pub(crate) const ARTIFACT_FILENAME: &str = "review-artifact.json";

/// Maximum re-ask retries after an invalid or missing emission. Research puts
/// first-retry recovery near 80% and second-retry above 99%; a third is wasted
/// tokens. The loop is fail-closed: an artifact that never validates is an error.
const MAX_REASK_RETRIES: usize = 2;

#[derive(Debug, Clone, Copy, ValueEnum)]
pub enum HarnessKind {
    Opencode,
    Omp,
    Fixture,
    ContainerOpencode,
}

#[derive(Debug, Clone)]
pub struct FixtureSubstrateConfig {
    pub output: PathBuf,
}

#[derive(Debug, Clone)]
pub struct OpenCodeSubstrateConfig {
    pub binary: String,
    pub attach: Option<String>,
    pub agent: Option<String>,
    pub model: Option<String>,
}

#[derive(Debug, Clone)]
pub struct OmpSubstrateConfig {
    pub binary: String,
    pub model: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ExecutionPlan {
    pub harness: String,
    pub command: String,
    pub args: Vec<String>,
    pub cwd: String,
    pub timeout_ms: u64,
    pub env_allowlist: Vec<String>,
    pub context_capabilities: ContextCapabilities,
    pub prompt_transport: String,
    pub private_material_in_argv: bool,
    pub workspace_mode: String,
    pub runtime_transcripts: Vec<String>,
}

#[derive(Debug, Clone)]
pub(crate) struct HarnessRun {
    pub artifact: ReviewArtifact,
    pub transcript: String,
    pub execution_plan: ExecutionPlan,
    pub telemetry: ReviewTelemetry,
}

pub(crate) fn run_fixture_substrate(
    request: &ReviewRequest,
    timeout: Duration,
    config: &FixtureSubstrateConfig,
) -> Result<HarnessRun> {
    let fixture_path = &config.output;
    let raw = fs::read_to_string(fixture_path)
        .with_context(|| format!("read fixture output {}", fixture_path.display()))?;
    let request_digest = request_digest(request)?;
    let capabilities = ContextCapabilities::from_request(request);
    let temp = tempfile::Builder::new()
        .prefix("cerberus-fixture-")
        .tempdir()
        .context("create private fixture tempdir")?;
    let workspace = RunWorkspace::prepare(request, temp.path())?;
    let mut child_request = request_with_workspace_paths(request, &workspace);
    let runtime_receipts =
        run_local_runtime_probes(&mut child_request, &workspace, temp.path(), timeout)?;
    // The fixture stands in for the agent: render its template and write the
    // result to the same out-path a real substrate would, then read it back
    // through the one shared parse path. No markers, no transcript scraping.
    let emitted = apply_fixture_template(&raw, request, &request_digest, &capabilities)?;
    let out_path = workspace.path().join(ARTIFACT_FILENAME);
    fs::write(&out_path, emitted.as_bytes())
        .with_context(|| format!("write fixture artifact {}", out_path.display()))?;
    let transcript = format!(
        "{}fixture wrote artifact to {}\n\n{}",
        runtime_probe_transcript(&runtime_receipts),
        out_path.display(),
        emitted
    );
    let artifact = read_artifact_file(&out_path)?;
    let plan = ExecutionPlan {
        harness: "fixture".to_string(),
        command: fixture_path.display().to_string(),
        args: Vec::new(),
        cwd: workspace.path().display().to_string(),
        timeout_ms: timeout.as_millis() as u64,
        env_allowlist: request.policy.allowed_env.clone(),
        context_capabilities: capabilities,
        prompt_transport: "fixture template".to_string(),
        private_material_in_argv: false,
        workspace_mode: workspace.mode().to_string(),
        runtime_transcripts: runtime_receipts
            .iter()
            .map(|receipt| receipt.artifact.uri.clone())
            .collect(),
    };
    Ok(HarnessRun {
        artifact,
        transcript,
        execution_plan: plan,
        telemetry: ReviewTelemetry::default(),
    })
}

#[derive(Clone, Copy)]
pub(crate) enum CommandSubstrateConfig<'a> {
    Opencode(&'a OpenCodeSubstrateConfig),
    Omp(&'a OmpSubstrateConfig),
}

pub(crate) fn run_command_substrate(
    substrate: CommandSubstrateConfig<'_>,
    request: &ReviewRequest,
    timeout: Duration,
    failure_transcript: Option<&Path>,
) -> Result<HarnessRun> {
    let request_digest = request_digest(request)?;
    let capabilities = ContextCapabilities::from_request(request);
    let temp = tempfile::Builder::new()
        .prefix("cerberus-")
        .tempdir()
        .context("create private prompt tempdir")?;
    let child_home = temp.path().join("home");
    let child_cache = temp.path().join("cache");
    let child_config = temp.path().join("config");
    let child_data = temp.path().join("data");
    for child_state_dir in [&child_home, &child_cache, &child_config, &child_data] {
        fs::create_dir_all(child_state_dir)
            .with_context(|| format!("create child state dir {}", child_state_dir.display()))?;
        set_private_directory_permissions(child_state_dir)?;
    }
    let workspace = RunWorkspace::prepare(request, temp.path())?;
    let mut child_request = request_with_workspace_paths(request, &workspace);
    let runtime_receipts =
        run_local_runtime_probes(&mut child_request, &workspace, temp.path(), timeout)?;
    // The agent writes its artifact here, inside the workspace it already has
    // write access to; the harness reads it back. One unambiguous file, not a
    // span scraped out of the transcript.
    let out_path = workspace.path().join(ARTIFACT_FILENAME);
    let prompt = build_master_prompt(&child_request, &capabilities, &request_digest, &out_path)?;
    let prompt_path = temp.path().join("master-prompt.md");
    fs::write(&prompt_path, prompt).context("write master prompt")?;
    set_private_permissions(&prompt_path)?;
    let request_path = temp.path().join("review-request.json");
    fs::write(&request_path, serde_json::to_vec_pretty(&child_request)?)
        .context("write review request")?;
    set_private_permissions(&request_path)?;
    if matches!(substrate, CommandSubstrateConfig::Opencode(_)) {
        write_opencode_config(
            &child_config,
            &opencode_allowed_paths(&workspace, &runtime_receipts),
        )?;
    }

    let (binary, args, plan_harness, prompt_transport) = command_for_substrate(
        substrate,
        CommandInput {
            cwd: workspace.path(),
            prompt_path: &prompt_path,
            request_path: &request_path,
            out_path: &out_path,
            request,
            capabilities: &capabilities,
            request_digest: &request_digest,
        },
    )?;

    let trusted_search_path = trusted_executable_search_path();
    let executable = resolve_executable_in(&binary, &trusted_search_path)?;

    let plan = ExecutionPlan {
        harness: plan_harness.to_string(),
        command: executable.display().to_string(),
        args: redact_prompt_path(&args),
        cwd: workspace.path().display().to_string(),
        timeout_ms: timeout.as_millis() as u64,
        env_allowlist: request.policy.allowed_env.clone(),
        context_capabilities: capabilities,
        prompt_transport: prompt_transport.to_string(),
        private_material_in_argv: false,
        workspace_mode: workspace.mode().to_string(),
        runtime_transcripts: runtime_receipts
            .iter()
            .map(|receipt| receipt.artifact.uri.clone())
            .collect(),
    };

    let spawn_attempt = |attempt_args: &[String]| -> Result<CommandOutput> {
        let start = Instant::now();
        let mut command = Command::new(&executable);
        command
            .args(attempt_args)
            .current_dir(workspace.path())
            .stdin(Stdio::null())
            .env_clear();
        for (key, value) in allowed_child_env(&request.policy.allowed_env) {
            command.env(key, value);
        }
        command.env("PATH", join_search_path(&trusted_search_path));
        command.env("HOME", &child_home);
        command.env("XDG_CACHE_HOME", &child_cache);
        command.env("XDG_CONFIG_HOME", &child_config);
        command.env("XDG_DATA_HOME", &child_data);
        configure_process_group(&mut command);
        let mut output = run_with_timeout(command, timeout)?;
        output.elapsed_ms = start.elapsed().as_millis();
        Ok(output)
    };

    let mut output = spawn_attempt(&args).with_context(|| format!("run {plan_harness} harness"))?;
    let telemetry = telemetry_for_substrate(substrate, &output.stdout);
    let mut transcript = runtime_probe_transcript(&runtime_receipts);
    append_attempt_transcript(&mut transcript, "initial", None, &output);

    // Read the emitted file and check it. While it is unacceptable, ask the same
    // OpenCode session to fix it, carrying the exact reason. Bounded and
    // fail-closed: only OpenCode can be re-asked (opencode_reask_args returns None
    // otherwise), so omp/fixture get one shot and a still-bad artifact falls
    // through to the validation gate below — never silently accepted.
    let mut artifact_result = read_artifact_file(&out_path);
    let mut attempt = 0;
    while let Err(reason) = evaluate_emission(&artifact_result, request) {
        if output.status == "timeout" {
            write_failure_transcript(failure_transcript, &transcript)?;
            let transcript_hint = failure_transcript
                .map(|path| format!("; transcript: {}", path.display()))
                .unwrap_or_default();
            return Err(anyhow!(
                "{plan_harness} harness timed out after {}ms before producing a valid ReviewArtifact.v1 ({reason}){transcript_hint}",
                output.elapsed_ms
            ));
        }
        if attempt >= MAX_REASK_RETRIES {
            break;
        }
        let Some(reask_args) =
            opencode_reask_args(substrate, &output.stdout, &reason, &out_path, &request_path)
        else {
            break;
        };
        attempt += 1;
        output = spawn_attempt(&reask_args).with_context(|| "run opencode re-ask")?;
        append_attempt_transcript(&mut transcript, "re-ask", Some(&reason), &output);
        artifact_result = read_artifact_file(&out_path);
    }

    let artifact = match artifact_result {
        Ok(artifact) => artifact,
        Err(err) => {
            write_failure_transcript(failure_transcript, &transcript)?;
            return Err(err);
        }
    };
    if let Err(err) = validate_process_status_matches_artifact(&output.status, &artifact) {
        write_failure_transcript(failure_transcript, &transcript)?;
        return Err(err);
    }
    Ok(HarnessRun {
        artifact,
        transcript,
        execution_plan: plan,
        telemetry,
    })
}

/// Read and parse the artifact the agent emitted to its out-path. A missing or
/// unparseable file is an error (the agent never produced a deliverable), which
/// the re-ask loop treats as a reason to ask again.
pub(crate) fn read_artifact_file(out_path: &Path) -> Result<ReviewArtifact> {
    let raw = fs::read_to_string(out_path)
        .with_context(|| format!("read emitted review artifact {}", out_path.display()))?;
    serde_json::from_str(&raw)
        .with_context(|| format!("parse ReviewArtifact.v1 emitted at {}", out_path.display()))
}

/// Evaluate an emitted artifact: `Ok(())` if it parsed and validates against the
/// request, `Err(reason)` carrying the exact failure to feed back into a re-ask
/// so the agent fixes the real problem rather than guessing.
fn evaluate_emission(
    artifact_result: &Result<ReviewArtifact>,
    request: &ReviewRequest,
) -> std::result::Result<(), String> {
    let artifact = artifact_result.as_ref().map_err(|err| {
        format!("the artifact file was missing or not valid ReviewArtifact.v1 JSON ({err:#})")
    })?;
    validate_artifact_for_request(artifact, request)
        .map_err(|err| format!("the artifact failed validation: {err}"))
}

/// First `sessionID` in an OpenCode JSON event stream — the run's root session.
/// A session must exist before it can spawn a subagent, so the root's first event
/// always precedes any child's. Even if that did not hold, continuing the wrong
/// session would re-read a still-invalid file and fail closed, never silently
/// accept.
fn first_opencode_session_id(stdout: &[u8]) -> Option<String> {
    String::from_utf8_lossy(stdout).lines().find_map(|line| {
        serde_json::from_str::<Value>(line)
            .ok()?
            .get("sessionID")
            .and_then(Value::as_str)
            .filter(|session| !session.is_empty())
            .map(str::to_string)
    })
}

/// Build the `opencode run --session <id>` re-ask that continues the review
/// session (captured from its prior output) and asks it to rewrite the out-path,
/// carrying the exact `reason`. Returns `None` for substrates that cannot
/// continue a session (omp/fixture) or when no session id was emitted — either
/// way the caller stops re-asking. This is the single gate that makes the re-ask
/// OpenCode-only.
fn opencode_reask_args(
    substrate: CommandSubstrateConfig<'_>,
    stdout: &[u8],
    reason: &str,
    out_path: &Path,
    request_path: &Path,
) -> Option<Vec<String>> {
    let CommandSubstrateConfig::Opencode(config) = substrate else {
        return None;
    };
    let session = first_opencode_session_id(stdout)?;
    let message = format!(
        "Your previous {filename} was rejected: {reason}. Fix exactly that problem and rewrite the COMPLETE corrected ReviewArtifact.v1 as a single raw JSON object to {out_path}, overwriting it. Write nothing else to that file — no Markdown fences, no prose.",
        filename = ARTIFACT_FILENAME,
        reason = reason,
        out_path = out_path.display(),
    );
    let mut args = vec![
        "run".to_string(),
        message,
        "--session".to_string(),
        session,
        "--format".to_string(),
        "json".to_string(),
        "--dir".to_string(),
        out_path.parent().unwrap_or(out_path).display().to_string(),
        "--file".to_string(),
        request_path.display().to_string(),
    ];
    push_opencode_optional_flags(&mut args, config);
    Some(args)
}

/// Append the optional `--model`/`--agent`/`--attach` flags an OpenCode run
/// carries. Shared by the initial command and the re-ask so the two cannot drift.
fn push_opencode_optional_flags(args: &mut Vec<String>, config: &OpenCodeSubstrateConfig) {
    for (flag, value) in [
        ("--model", &config.model),
        ("--agent", &config.agent),
        ("--attach", &config.attach),
    ] {
        if let Some(value) = value {
            args.push(flag.to_string());
            args.push(value.clone());
        }
    }
}

/// Append one attempt's command result to the running transcript. The re-ask
/// reason is recorded so the evidence shows the exact error that was carried
/// back into the next turn.
fn append_attempt_transcript(
    transcript: &mut String,
    label: &str,
    reason: Option<&str>,
    output: &CommandOutput,
) {
    transcript.push_str(&format!("[attempt: {label}]\n"));
    if let Some(reason) = reason {
        transcript.push_str(&format!("re-ask reason: {reason}\n"));
    }
    transcript.push_str(&format!(
        "exit_status: {}\nelapsed_ms: {}\n\n[stdout]\n{}\n\n[stderr]\n{}\n\n",
        output.status,
        output.elapsed_ms,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    ));
}

fn command_for_substrate(
    substrate: CommandSubstrateConfig<'_>,
    input: CommandInput<'_>,
) -> Result<(String, Vec<String>, &'static str, &'static str)> {
    match substrate {
        CommandSubstrateConfig::Opencode(config) => {
            let message = build_opencode_message(
                input.request,
                input.capabilities,
                input.request_digest,
                input.out_path,
            )
            .context("build opencode message")?;
            let mut args = vec![
                "run".to_string(),
                message,
                "--format".to_string(),
                "json".to_string(),
                "--dir".to_string(),
                input.cwd.display().to_string(),
                "--file".to_string(),
                input.request_path.display().to_string(),
            ];
            push_opencode_optional_flags(&mut args, config);
            Ok((
                config.binary.clone(),
                args,
                "opencode",
                "private request file attachment plus argv instructions",
            ))
        }
        CommandSubstrateConfig::Omp(config) => {
            let mut args = vec![
                "-p".to_string(),
                "--no-session".to_string(),
                "--no-pty".to_string(),
                "--no-extensions".to_string(),
                "--no-skills".to_string(),
                "--no-rules".to_string(),
                "--cwd".to_string(),
                input.cwd.display().to_string(),
            ];
            if let Some(model) = &config.model {
                args.push("--model".to_string());
                args.push(model.clone());
            }
            args.push(format!("@{}", input.prompt_path.display()));
            Ok((config.binary.clone(), args, "omp", "private prompt file"))
        }
    }
}

fn request_with_workspace_paths(
    request: &ReviewRequest,
    workspace: &RunWorkspace,
) -> ReviewRequest {
    let mut child_request = request.clone();
    if let Some(head) = &mut child_request.context.workspaces.head {
        head.path = workspace.path().display().to_string();
    }
    if let (Some(base), Some(base_path)) = (
        &mut child_request.context.workspaces.base,
        workspace.base_path(),
    ) {
        base.path = base_path.display().to_string();
    }
    child_request
}

fn write_opencode_config(config_home: &Path, workspace_paths: &[PathBuf]) -> Result<()> {
    let config_dir = config_home.join("opencode");
    fs::create_dir_all(&config_dir)
        .with_context(|| format!("create OpenCode config dir {}", config_dir.display()))?;
    set_private_directory_permissions(&config_dir)?;
    let mut external_directory = serde_json::Map::new();
    for workspace_path in workspace_paths {
        let workspace = workspace_path.display().to_string();
        let workspace_children = format!("{workspace}/**");
        external_directory.insert(workspace, Value::String("allow".to_string()));
        external_directory.insert(workspace_children, Value::String("allow".to_string()));
    }
    // The review agent explores autonomously with a full toolset (read, grep,
    // shell for ripgrep/ast-grep/git, web research). Isolation comes from the
    // disposable detached worktree plus the scrubbed env (only explicitly allowed
    // vars reach the child), not from denying tools. Untrusted-PR isolation
    // (network egress + credential handling) is a separate container profile
    // tracked in backlog 013.
    let config = serde_json::json!({
        "$schema": "https://opencode.ai/config.json",
        "permission": {
            "external_directory": external_directory,
            "edit": "allow",
            "bash": "allow",
            "webfetch": "allow",
            "websearch": "allow"
        }
    });
    let config_path = config_dir.join("opencode.json");
    fs::write(&config_path, serde_json::to_vec_pretty(&config)?)
        .with_context(|| format!("write OpenCode config {}", config_path.display()))?;
    set_private_permissions(&config_path)
}

fn opencode_allowed_paths(
    workspace: &RunWorkspace,
    runtime_receipts: &[RuntimeProbeReceipt],
) -> Vec<PathBuf> {
    let mut paths = workspace.allowed_paths();
    for receipt in runtime_receipts {
        let transcript_path = Path::new(&receipt.artifact.uri);
        if let Some(parent) = transcript_path.parent() {
            let parent = parent.to_path_buf();
            if !paths.iter().any(|path| path == &parent) {
                paths.push(parent);
            }
        }
    }
    paths
}

#[derive(Debug)]
struct RunWorkspace {
    path: PathBuf,
    base_path: Option<PathBuf>,
    mode: String,
    cleanup: Vec<WorktreeCleanup>,
}

#[derive(Debug)]
struct WorktreeCleanup {
    source: PathBuf,
    path: PathBuf,
}

impl RunWorkspace {
    fn prepare(request: &ReviewRequest, temp_root: &Path) -> Result<Self> {
        if let Some(head) = &request.context.workspaces.head {
            let base = request
                .context
                .workspaces
                .base
                .as_ref()
                .map(|base| {
                    Self::prepare_worktree(
                        Path::new(&base.path),
                        base.sha.as_deref(),
                        temp_root,
                        "repo-base",
                        "repo_base",
                    )
                })
                .transpose()?;
            let head = Self::prepare_worktree(
                Path::new(&head.path),
                head.sha.as_deref(),
                temp_root,
                "repo-head",
                "repo_head",
            )?;
            let mode = if base.is_some() {
                "repo_base_head_worktrees"
            } else {
                "repo_head_worktree"
            };
            return Ok(Self::from_prepared(head, base, mode));
        }
        if request.context.workspaces.base.is_some() {
            return Err(anyhow!("repo_base workspace requires repo_head workspace"));
        }
        let packet = temp_root.join("packet");
        fs::create_dir_all(&packet).context("create diff-only packet workspace")?;
        let request_path = packet.join("request.json");
        fs::write(&request_path, serde_json::to_vec_pretty(request)?)
            .context("write packet request")?;
        let diff_path = packet.join("change.diff");
        fs::write(&diff_path, request.change.diff.body.as_bytes()).context("write packet diff")?;
        set_private_permissions(&request_path)?;
        set_private_permissions(&diff_path)?;

        // An empty diff has nothing to review; validate_request rejects it before
        // any binary reaches the kernel, so a real CLI run never hits this. Only a
        // library caller that skips validation could — and even then it gets the
        // same private packet dir as any other diff-only run, never a real cwd
        // (backlog 017).
        let mode = if request.change.diff.body.trim().is_empty() {
            "empty_diff_packet"
        } else {
            "diff_packet"
        };
        Ok(Self::with_packet(packet, mode))
    }

    fn prepare_worktree(
        source: &Path,
        sha: Option<&str>,
        temp_root: &Path,
        name: &str,
        label: &str,
    ) -> Result<PreparedWorktree> {
        let sha = sha.ok_or_else(|| {
            anyhow!(
                "{label} workspace {} requires a sha for disposable review checkout",
                source.display()
            )
        })?;
        let worktree = temp_root.join(name);
        let output = Command::new("git")
            .arg("-C")
            .arg(source)
            .args(["worktree", "add", "--detach"])
            .arg(&worktree)
            .arg(sha)
            .output()
            .with_context(|| {
                format!(
                    "create disposable {label} review worktree from {}",
                    source.display()
                )
            })?;
        if !output.status.success() {
            return Err(anyhow!(
                "create disposable {label} review worktree from {} failed: {}",
                source.display(),
                String::from_utf8_lossy(&output.stderr)
            ));
        }
        Ok(PreparedWorktree {
            path: worktree.clone(),
            cleanup: WorktreeCleanup {
                source: source.to_path_buf(),
                path: worktree,
            },
        })
    }

    fn from_prepared(head: PreparedWorktree, base: Option<PreparedWorktree>, mode: &str) -> Self {
        let mut cleanup = vec![head.cleanup];
        let base_path = base.as_ref().map(|base| base.path.clone());
        if let Some(base) = base {
            cleanup.push(base.cleanup);
        }
        Self {
            path: head.path,
            base_path,
            mode: mode.to_string(),
            cleanup,
        }
    }

    fn with_packet(path: PathBuf, mode: &str) -> Self {
        Self {
            path,
            base_path: None,
            mode: mode.to_string(),
            cleanup: Vec::new(),
        }
    }

    fn path(&self) -> &Path {
        &self.path
    }

    fn base_path(&self) -> Option<&Path> {
        self.base_path.as_deref()
    }

    fn allowed_paths(&self) -> Vec<PathBuf> {
        let mut paths = vec![self.path.clone()];
        if let Some(base_path) = &self.base_path {
            if base_path != &self.path {
                paths.push(base_path.clone());
            }
        }
        paths
    }

    fn mode(&self) -> &str {
        &self.mode
    }
}

impl Drop for RunWorkspace {
    fn drop(&mut self) {
        for cleanup in &self.cleanup {
            let _ = Command::new("git")
                .arg("-C")
                .arg(&cleanup.source)
                .args(["worktree", "remove", "--force"])
                .arg(&cleanup.path)
                .output();
        }
    }
}

#[derive(Debug)]
struct PreparedWorktree {
    path: PathBuf,
    cleanup: WorktreeCleanup,
}

#[derive(Debug, Clone)]
struct RuntimeProbeReceipt {
    artifact: ContextArtifact,
    transcript: String,
}

fn run_local_runtime_probes(
    request: &mut ReviewRequest,
    workspace: &RunWorkspace,
    temp_root: &Path,
    timeout: Duration,
) -> Result<Vec<RuntimeProbeReceipt>> {
    if request.context.local_runtime.is_empty() {
        return Ok(Vec::new());
    }
    if !request.policy.allow_local_runtime {
        return Err(anyhow!(
            "local runtime targets require policy.allow_local_runtime"
        ));
    }

    let targets = request.context.local_runtime.clone();
    let allowed_env = request.policy.allowed_env.clone();
    let probe_dir = temp_root.join("runtime-probes");
    fs::create_dir_all(&probe_dir)
        .with_context(|| format!("create runtime probe dir {}", probe_dir.display()))?;
    set_private_directory_permissions(&probe_dir)?;
    let search_path = trusted_executable_search_path();
    let mut artifacts = Vec::new();
    for (index, target) in targets.iter().enumerate() {
        let artifact = run_local_runtime_probe(
            index,
            target,
            workspace,
            &probe_dir,
            &allowed_env,
            &search_path,
            timeout,
        )?;
        artifacts.push(artifact);
    }
    request
        .context
        .artifacts
        .extend(artifacts.iter().map(|receipt| receipt.artifact.clone()));
    Ok(artifacts)
}

fn run_local_runtime_probe(
    index: usize,
    target: &RuntimeTarget,
    workspace: &RunWorkspace,
    probe_dir: &Path,
    allowed_env: &[String],
    search_path: &[PathBuf],
    timeout: Duration,
) -> Result<RuntimeProbeReceipt> {
    if target.kind != "command" {
        return Err(anyhow!(
            "unsupported local runtime target kind {:?}; expected command",
            target.kind
        ));
    }
    let executable = resolve_executable_in(&target.command, search_path)?;
    let cwd = runtime_probe_cwd(target, workspace.path())?;
    let start = Instant::now();
    let mut command = Command::new(&executable);
    command
        .args(&target.args)
        .current_dir(&cwd)
        .stdin(Stdio::null())
        .env_clear();
    for (key, value) in allowed_child_env(allowed_env) {
        command.env(key, value);
    }
    command.env("PATH", join_search_path(search_path));
    configure_process_group(&mut command);

    let output = run_with_timeout(command, timeout).with_context(|| {
        format!(
            "run local runtime target {} {}",
            target.command,
            target.args.join(" ")
        )
    })?;
    let elapsed_ms = start.elapsed().as_millis();
    let transcript = format!(
        "kind: local_runtime_command\ncommand: {}\nargs: {:?}\ncwd: {}\nexit_status: {}\nelapsed_ms: {}\n\n[stdout]\n{}\n\n[stderr]\n{}",
        executable.display(),
        target.args,
        cwd.display(),
        output.status,
        elapsed_ms,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let transcript_path = probe_dir.join(format!("local-runtime-{index}.txt"));
    fs::write(&transcript_path, transcript.as_bytes())
        .with_context(|| format!("write runtime transcript {}", transcript_path.display()))?;
    set_private_permissions(&transcript_path)?;
    let artifact = ContextArtifact {
        kind: "local_runtime_transcript".to_string(),
        uri: transcript_path.display().to_string(),
        digest: Some(sha256_digest(transcript.as_bytes())),
    };
    Ok(RuntimeProbeReceipt {
        artifact,
        transcript,
    })
}

fn runtime_probe_cwd(target: &RuntimeTarget, workspace_path: &Path) -> Result<PathBuf> {
    let Some(raw_cwd) = target.cwd.as_deref() else {
        return Ok(workspace_path.to_path_buf());
    };
    let relative = Path::new(raw_cwd);
    if relative.is_absolute() {
        return Err(anyhow!(
            "local runtime cwd must be relative to the disposable review workspace: {raw_cwd}"
        ));
    }
    if relative
        .components()
        .any(|component| matches!(component, std::path::Component::ParentDir))
    {
        return Err(anyhow!(
            "local runtime cwd cannot escape the disposable review workspace: {raw_cwd}"
        ));
    }
    let cwd = workspace_path.join(relative);
    if !cwd.is_dir() {
        return Err(anyhow!(
            "local runtime cwd does not exist inside review workspace: {}",
            cwd.display()
        ));
    }
    Ok(cwd)
}

fn runtime_probe_transcript(receipts: &[RuntimeProbeReceipt]) -> String {
    if receipts.is_empty() {
        return String::new();
    }
    let mut output = String::from("[local_runtime]\n");
    for (index, receipt) in receipts.iter().enumerate() {
        output.push_str(&format!(
            "--- local-runtime-{index}: {} ---\n{}\n",
            receipt.artifact.uri, receipt.transcript
        ));
    }
    output.push('\n');
    output
}

#[derive(Debug, Clone, Copy)]
struct CommandInput<'a> {
    cwd: &'a Path,
    prompt_path: &'a Path,
    request_path: &'a Path,
    out_path: &'a Path,
    request: &'a ReviewRequest,
    capabilities: &'a ContextCapabilities,
    request_digest: &'a str,
}

#[derive(Debug)]
struct CommandOutput {
    status: String,
    stdout: Vec<u8>,
    stderr: Vec<u8>,
    elapsed_ms: u128,
}

fn validate_process_status_matches_artifact(status: &str, artifact: &ReviewArtifact) -> Result<()> {
    let successful = status.contains("exit status: 0") || status == "0";
    if successful {
        return Ok(());
    }
    let degraded_or_failed = matches!(
        artifact.lifecycle_state,
        LifecycleState::CompletedDegraded | LifecycleState::Failed | LifecycleState::Cancelled
    );
    let has_matching_receipt = artifact.receipts.iter().any(|receipt| {
        matches!(
            receipt.status,
            ReceiptStatus::Timeout | ReceiptStatus::Error
        ) || receipt.error.is_some()
    });
    if degraded_or_failed && has_matching_receipt {
        return Ok(());
    }
    Err(anyhow!(
        "child process status {status:?} cannot produce lifecycle {:?} without timeout/error receipt",
        artifact.lifecycle_state
    ))
}

fn run_with_timeout(mut command: Command, timeout: Duration) -> Result<CommandOutput> {
    let stdout_capture = tempfile::NamedTempFile::new().context("create stdout capture file")?;
    let stderr_capture = tempfile::NamedTempFile::new().context("create stderr capture file")?;
    command.stdout(Stdio::from(
        stdout_capture
            .reopen()
            .context("open stdout capture writer")?,
    ));
    command.stderr(Stdio::from(
        stderr_capture
            .reopen()
            .context("open stderr capture writer")?,
    ));
    let mut child = command.spawn().context("spawn command")?;
    let start = Instant::now();
    loop {
        if let Some(status) = child.try_wait().context("poll command")? {
            return Ok(CommandOutput {
                status: status.to_string(),
                stdout: read_capped_file(stdout_capture.path()).context("read stdout capture")?,
                stderr: read_capped_file(stderr_capture.path()).context("read stderr capture")?,
                elapsed_ms: 0,
            });
        }
        if start.elapsed() >= timeout {
            kill_process_tree(&mut child);
            child.wait().context("collect killed command status")?;
            return Ok(CommandOutput {
                status: "timeout".to_string(),
                stdout: read_capped_file(stdout_capture.path()).context("read stdout capture")?,
                stderr: read_capped_file(stderr_capture.path()).context("read stderr capture")?,
                elapsed_ms: 0,
            });
        }
        std::thread::sleep(Duration::from_millis(100));
    }
}

fn allowed_child_env(allowed_env: &[String]) -> BTreeMap<String, String> {
    allowed_env
        .iter()
        .filter_map(|key| std::env::var(key).ok().map(|value| (key.clone(), value)))
        .collect()
}

fn trusted_executable_search_path() -> Vec<PathBuf> {
    let mut paths = vec![
        PathBuf::from("/usr/bin"),
        PathBuf::from("/bin"),
        PathBuf::from("/usr/sbin"),
        PathBuf::from("/sbin"),
    ];
    for candidate in ["/opt/homebrew/bin", "/usr/local/bin"] {
        if Path::new(candidate).is_dir() {
            paths.push(PathBuf::from(candidate));
        }
    }
    if let Some(home) = std::env::var_os("HOME").map(PathBuf::from) {
        for relative in [".bun/bin", ".opencode/bin", ".local/bin"] {
            let candidate = home.join(relative);
            if candidate.is_dir() {
                paths.push(candidate);
            }
        }
    }
    paths
}

fn join_search_path(paths: &[PathBuf]) -> String {
    std::env::join_paths(paths)
        .map(|joined| joined.to_string_lossy().into_owned())
        .unwrap_or_else(|_| {
            paths
                .iter()
                .map(|path| path.display().to_string())
                .collect::<Vec<_>>()
                .join(PATH_LIST_SEPARATOR)
        })
}

#[cfg(windows)]
const PATH_LIST_SEPARATOR: &str = ";";

#[cfg(not(windows))]
const PATH_LIST_SEPARATOR: &str = ":";

fn resolve_executable_in(binary: &str, search_paths: &[PathBuf]) -> Result<PathBuf> {
    let path = Path::new(binary);
    if path.is_absolute() {
        if is_executable_file(path) {
            return Ok(path.to_path_buf());
        }
        return Err(anyhow!(
            "absolute harness binary is not executable: {}",
            path.display()
        ));
    }
    if binary.contains('/') || binary.contains('\\') {
        return Err(anyhow!(
            "harness binary must be an absolute path or a bare name from the trusted search path: {binary}"
        ));
    }
    search_paths
        .iter()
        .map(|path| path.join(binary))
        .find(|candidate| is_executable_file(candidate))
        .ok_or_else(|| {
            anyhow!(
                "harness binary {binary:?} was not found in trusted search path: {}",
                join_search_path(search_paths)
            )
        })
}

#[cfg(unix)]
fn is_executable_file(path: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    fs::metadata(path)
        .map(|metadata| metadata.is_file() && metadata.permissions().mode() & 0o111 != 0)
        .unwrap_or(false)
}

#[cfg(not(unix))]
fn is_executable_file(path: &Path) -> bool {
    path.is_file()
}

#[cfg(unix)]
fn configure_process_group(command: &mut Command) {
    use std::os::unix::process::CommandExt;
    unsafe {
        command.pre_exec(|| {
            if libc::setpgid(0, 0) == -1 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }
}

#[cfg(not(unix))]
fn configure_process_group(_command: &mut Command) {}

#[cfg(unix)]
fn kill_process_tree(child: &mut std::process::Child) {
    let pid = child.id() as i32;
    unsafe {
        libc::kill(-pid, libc::SIGKILL);
    }
    let _ = child.kill();
}

#[cfg(not(unix))]
fn kill_process_tree(child: &mut std::process::Child) {
    let _ = child.kill();
}

const OUTPUT_CAPTURE_CAP: usize = 64_000_000;
const OUTPUT_TRUNCATION_MARKER: &[u8] = b"\n...[cerberus truncated middle]...\n";

fn read_capped_file(path: &Path) -> Result<Vec<u8>> {
    let mut file = fs::File::open(path)?;
    let len = file.metadata()?.len() as usize;
    if len <= OUTPUT_CAPTURE_CAP {
        let mut bytes = Vec::with_capacity(len);
        file.read_to_end(&mut bytes)?;
        return Ok(bytes);
    }

    let available = OUTPUT_CAPTURE_CAP.saturating_sub(OUTPUT_TRUNCATION_MARKER.len());
    if available == 0 {
        file.seek(SeekFrom::End(-(OUTPUT_CAPTURE_CAP as i64)))?;
        let mut bytes = Vec::with_capacity(OUTPUT_CAPTURE_CAP);
        file.read_to_end(&mut bytes)?;
        return Ok(bytes);
    }

    let head_len = available / 2;
    let tail_len = available - head_len;
    let mut bytes = Vec::with_capacity(OUTPUT_CAPTURE_CAP);
    let mut head = vec![0; head_len];
    file.read_exact(&mut head)?;
    bytes.extend_from_slice(&head);
    bytes.extend_from_slice(OUTPUT_TRUNCATION_MARKER);
    file.seek(SeekFrom::End(-(tail_len as i64)))?;
    let mut tail = vec![0; tail_len];
    file.read_exact(&mut tail)?;
    bytes.extend_from_slice(&tail);
    Ok(bytes)
}

fn telemetry_for_substrate(
    substrate: CommandSubstrateConfig<'_>,
    stdout: &[u8],
) -> ReviewTelemetry {
    match substrate {
        CommandSubstrateConfig::Opencode(config) => {
            opencode_telemetry(stdout, config.model.as_deref())
        }
        CommandSubstrateConfig::Omp(config) => omp_telemetry(config.model.as_deref()),
    }
}

fn redact_prompt_path(args: &[String]) -> Vec<String> {
    args.iter()
        .map(|arg| {
            if arg.starts_with('@') {
                "@<prompt-file>".to_string()
            } else if arg.contains("/master-prompt.md") {
                "<prompt-file>".to_string()
            } else if arg.contains("/review-request.json") {
                "<request-file>".to_string()
            } else {
                arg.clone()
            }
        })
        .collect()
}

fn apply_fixture_template(
    raw: &str,
    request: &ReviewRequest,
    digest: &str,
    capabilities: &ContextCapabilities,
) -> Result<String> {
    let capabilities_json = serde_json::to_string(capabilities)?;
    let mut replacements = BTreeMap::new();
    replacements.insert("{{request_id}}", request.request_id.clone());
    replacements.insert("{{request_digest}}", digest.to_string());
    replacements.insert("{{context_capabilities}}", capabilities_json);
    replacements.insert("{{artifact_id}}", format!("artifact-{}", Uuid::new_v4()));
    replacements.insert("{{now}}", unix_timestamp_string());
    let mut rendered = raw.to_string();
    for (needle, replacement) in replacements {
        rendered = rendered.replace(needle, &replacement);
    }
    Ok(rendered)
}

fn write_failure_transcript(path: Option<&Path>, transcript: &str) -> Result<()> {
    let Some(path) = path else {
        return Ok(());
    };
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).with_context(|| format!("create {}", parent.display()))?;
    }
    fs::write(path, transcript)
        .with_context(|| format!("write failure transcript {}", path.display()))
}

fn unix_timestamp_string() -> String {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    format!("{seconds}")
}

#[cfg(unix)]
pub(crate) fn set_private_permissions(path: &Path) -> Result<()> {
    use std::os::unix::fs::PermissionsExt;
    let mut permissions = fs::metadata(path)?.permissions();
    permissions.set_mode(0o600);
    fs::set_permissions(path, permissions)?;
    Ok(())
}

#[cfg(not(unix))]
pub(crate) fn set_private_permissions(_path: &Path) -> Result<()> {
    Ok(())
}

#[cfg(unix)]
pub(crate) fn set_private_directory_permissions(path: &Path) -> Result<()> {
    use std::os::unix::fs::PermissionsExt;
    let mut permissions = fs::metadata(path)?.permissions();
    permissions.set_mode(0o700);
    fs::set_permissions(path, permissions)?;
    Ok(())
}

#[cfg(not(unix))]
pub(crate) fn set_private_directory_permissions(_path: &Path) -> Result<()> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[cfg(unix)]
    use std::os::unix::fs::PermissionsExt;

    fn test_request() -> ReviewRequest {
        serde_json::from_value::<ReviewRequest>(serde_json::json!({
            "schema_version": "cerberus.review_request.v1",
            "request_id": "req-1",
            "source": {"kind": "fixture", "metadata": {}},
            "change": {
                "title": "change",
                "diff": {"format": "unified", "body": "diff --git a/src/lib.rs b/src/lib.rs\n"},
                "files": []
            },
            "context": {},
            "policy": {}
        }))
        .unwrap()
    }

    // Backlog 017: an empty diff has nothing to review and validate_request
    // rejects it before any real CLI path reaches the kernel -- but a library
    // caller of ReviewKernel::review that skips validation could still hit
    // this. Before this ticket, that case resolved the workspace to the
    // caller's real cwd; since file emission writes review-artifact.json
    // straight into the resolved workspace, that would have dropped the file
    // into a real checkout. Pins that it now always resolves under the
    // private per-run tempdir, the same as any other diff-only request.
    #[test]
    fn empty_diff_request_still_resolves_to_a_private_tempdir_workspace() {
        let mut request = test_request();
        request.change.diff.body = String::new();
        let temp = tempfile::Builder::new()
            .prefix("cerberus-empty-diff-test-")
            .tempdir()
            .unwrap();

        let workspace = RunWorkspace::prepare(&request, temp.path()).unwrap();

        assert!(
            workspace.path().starts_with(temp.path()),
            "empty-diff workspace {} must live under the private tempdir {}, never a real caller cwd",
            workspace.path().display(),
            temp.path().display()
        );
        assert_eq!(workspace.mode, "empty_diff_packet");
    }

    #[test]
    fn reads_artifact_emitted_to_file() {
        let temp = tempfile::tempdir().unwrap();
        let out_path = temp.path().join(ARTIFACT_FILENAME);
        fs::write(&out_path, minimal_artifact_json()).unwrap();

        let artifact = read_artifact_file(&out_path).unwrap();

        assert_eq!(artifact.request_id, "req-1");
    }

    #[test]
    fn missing_emission_file_is_an_error() {
        let temp = tempfile::tempdir().unwrap();
        assert!(read_artifact_file(&temp.path().join("absent.json")).is_err());
    }

    #[test]
    fn unparseable_emission_file_is_an_error() {
        let temp = tempfile::tempdir().unwrap();
        let out_path = temp.path().join(ARTIFACT_FILENAME);
        fs::write(&out_path, "this is not a review artifact").unwrap();

        assert!(read_artifact_file(&out_path).is_err());
    }

    #[test]
    fn captures_root_session_id_from_opencode_events() {
        let stdout = b"{\"type\":\"step_start\",\"sessionID\":\"ses_root\",\"part\":{}}\n{\"type\":\"step_finish\",\"sessionID\":\"ses_root\"}\n";

        assert_eq!(
            first_opencode_session_id(stdout).as_deref(),
            Some("ses_root")
        );
    }

    #[test]
    fn evaluate_emission_carries_the_validation_error() {
        let request = test_request();
        // Parses fine but its request_digest cannot match the request digest.
        let artifact: ReviewArtifact = serde_json::from_str(&minimal_artifact_json()).unwrap();

        let reason = evaluate_emission(&Ok(artifact), &request).unwrap_err();

        assert!(
            reason.contains("failed validation"),
            "reason should name the validation failure: {reason}"
        );
        assert!(
            reason.contains("request digest"),
            "reason should carry the exact validator message: {reason}"
        );
    }

    #[test]
    fn evaluate_emission_carries_the_parse_error() {
        let request = test_request();
        let parse_error = read_artifact_file(Path::new("/cerberus/does-not-exist.json"));

        let reason = evaluate_emission(&parse_error, &request).unwrap_err();

        assert!(
            reason.contains("missing or not valid"),
            "reason should explain the file was unusable: {reason}"
        );
    }

    #[test]
    fn evaluate_emission_accepts_a_valid_artifact() {
        let request = test_request();
        let mut artifact: ReviewArtifact = serde_json::from_str(&minimal_artifact_json()).unwrap();
        artifact.request_id = request.request_id.clone();
        artifact.request_digest = request_digest(&request).unwrap();
        artifact.context_capabilities = ContextCapabilities::from_request(&request);

        assert!(evaluate_emission(&Ok(artifact), &request).is_ok());
    }

    #[test]
    fn opencode_reask_continues_the_session_and_names_the_out_path() {
        let config = test_opencode_config();
        let stdout = b"{\"type\":\"step_start\",\"sessionID\":\"ses_root\"}\n";
        let out_path = Path::new("/work/repo/review-artifact.json");
        let request_path = Path::new("/tmp/cerberus/review-request.json");

        let args = opencode_reask_args(
            CommandSubstrateConfig::Opencode(&config),
            stdout,
            "the artifact failed validation: artifact request digest mismatch",
            out_path,
            request_path,
        )
        .unwrap();

        assert!(args
            .windows(2)
            .any(|pair| pair == ["--session", "ses_root"]));
        assert!(args.windows(2).any(|pair| pair == ["--format", "json"]));
        assert!(args.windows(2).any(|pair| pair == ["--dir", "/work/repo"]));
        let message = &args[1];
        assert!(message.contains("/work/repo/review-artifact.json"));
        assert!(message.contains("request digest mismatch"));
    }

    #[test]
    fn omp_substrate_cannot_be_re_asked() {
        let config = OmpSubstrateConfig {
            binary: "omp".to_string(),
            model: None,
        };
        let stdout = b"{\"type\":\"step_start\",\"sessionID\":\"ses_root\"}\n";
        assert!(opencode_reask_args(
            CommandSubstrateConfig::Omp(&config),
            stdout,
            "reason",
            Path::new("/work/review-artifact.json"),
            Path::new("/tmp/request.json"),
        )
        .is_none());
    }

    #[cfg(unix)]
    #[test]
    fn private_directory_permissions_remain_traversable() {
        let temp = tempfile::tempdir().unwrap();
        let dir = temp.path().join("state");
        fs::create_dir(&dir).unwrap();

        set_private_directory_permissions(&dir).unwrap();

        let mode = fs::metadata(&dir).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o700);
    }

    #[test]
    fn opencode_config_grants_full_toolset_within_review_workspace() {
        let temp = tempfile::tempdir().unwrap();
        let workspace = temp.path().join("repo-head");
        fs::create_dir(&workspace).unwrap();

        write_opencode_config(temp.path(), std::slice::from_ref(&workspace)).unwrap();

        let config_path = temp.path().join("opencode/opencode.json");
        let config: Value =
            serde_json::from_str(&fs::read_to_string(config_path).unwrap()).unwrap();
        for tool in ["edit", "bash", "webfetch", "websearch"] {
            assert_eq!(
                config
                    .pointer(&format!("/permission/{tool}"))
                    .and_then(Value::as_str),
                Some("allow"),
                "review agent should have {tool} allowed for autonomous exploration"
            );
        }
        let escaped_workspace = workspace
            .display()
            .to_string()
            .replace('~', "~0")
            .replace('/', "~1");
        assert_eq!(
            config
                .pointer(&format!(
                    "/permission/external_directory/{escaped_workspace}"
                ))
                .and_then(Value::as_str),
            Some("allow")
        );
    }

    #[test]
    fn opencode_allowed_paths_include_runtime_probe_directory() {
        let temp = tempfile::tempdir().unwrap();
        let workspace = RunWorkspace {
            path: temp.path().join("repo-head"),
            base_path: None,
            mode: "repo_head_worktree".to_string(),
            cleanup: Vec::new(),
        };
        let probe_dir = temp.path().join("runtime-probes");
        let receipts = vec![RuntimeProbeReceipt {
            artifact: ContextArtifact {
                kind: "local_runtime_transcript".to_string(),
                uri: probe_dir.join("local-runtime-0.txt").display().to_string(),
                digest: None,
            },
            transcript: "kind: local_runtime_command".to_string(),
        }];

        let paths = opencode_allowed_paths(&workspace, &receipts);

        assert!(paths.contains(&workspace.path));
        assert!(paths.contains(&probe_dir));
    }

    #[test]
    fn bare_substrate_binary_resolves_only_from_trusted_search_path() {
        let temp = tempfile::tempdir().unwrap();
        let hostile_dir = temp.path().join("hostile-bin");
        let trusted_dir = temp.path().join("trusted-bin");
        fs::create_dir(&hostile_dir).unwrap();
        fs::create_dir(&trusted_dir).unwrap();
        let binary_name = "cerberus-test-opencode";
        let hostile_binary = hostile_dir.join(binary_name);
        let trusted_binary = trusted_dir.join(binary_name);
        fs::write(&hostile_binary, "#!/bin/sh\nexit 1\n").unwrap();
        fs::write(&trusted_binary, "#!/bin/sh\nexit 0\n").unwrap();
        set_executable(&hostile_binary);
        set_executable(&trusted_binary);

        let resolved = resolve_executable_in(binary_name, &[trusted_dir]).unwrap();

        assert_eq!(resolved, trusted_binary);
    }

    #[test]
    fn relative_substrate_binary_paths_are_rejected() {
        assert!(resolve_executable_in("./opencode", &[]).is_err());
    }

    #[cfg(unix)]
    fn set_executable(path: &Path) {
        let mut permissions = fs::metadata(path).unwrap().permissions();
        permissions.set_mode(0o700);
        fs::set_permissions(path, permissions).unwrap();
    }

    #[cfg(not(unix))]
    fn set_executable(_path: &Path) {}

    #[cfg(unix)]
    #[test]
    fn run_with_timeout_captures_stdout_larger_than_pipe_buffer() {
        let mut command = Command::new("sh");
        command.args(["-c", "yes x | head -c 200000"]);

        let output = run_with_timeout(command, Duration::from_secs(5)).unwrap();

        assert!(output.status.contains('0'));
        assert_eq!(output.stdout.len(), 200000);
    }

    // Backlog 008: bounded output was previously proven only by a
    // #[cfg(test)]-only reimplementation of the cap logic, never the
    // production read_capped_file path. Drives real bytes past the cap
    // through the actual function so a regression (e.g. someone "simplifies"
    // away the truncation branch) fails a test, not just a code review.
    #[test]
    fn read_capped_file_truncates_the_middle_of_oversized_output() {
        use std::io::Write;

        let file = tempfile::NamedTempFile::new().unwrap();
        let head_marker = b"HEAD_MARKER_BEGIN";
        let tail_marker = b"TAIL_MARKER_END";
        let total_len = OUTPUT_CAPTURE_CAP + 1_000_000;
        {
            let mut writer = std::io::BufWriter::new(file.reopen().unwrap());
            writer.write_all(head_marker).unwrap();
            let filler_len = total_len - head_marker.len() - tail_marker.len();
            writer.write_all(&vec![b'x'; filler_len]).unwrap();
            writer.write_all(tail_marker).unwrap();
            writer.flush().unwrap();
        }

        let bytes = read_capped_file(file.path()).unwrap();

        assert_eq!(
            bytes.len(),
            OUTPUT_CAPTURE_CAP,
            "capped output must never exceed the cap regardless of input size"
        );
        assert!(
            bytes.starts_with(head_marker),
            "the head of the output must survive truncation"
        );
        assert!(
            bytes.ends_with(tail_marker),
            "the tail of the output must survive truncation"
        );
        let text = String::from_utf8_lossy(&bytes);
        assert!(
            text.contains("[cerberus truncated middle]"),
            "truncation must be visible in the captured output, not silent"
        );
    }

    // Backlog 008: the orphan-kill machinery (setpgid at spawn + kill(-pid)
    // on timeout) had zero coverage — a silent regression here leaves a
    // credential-holding grandchild process running unbounded after Cerberus
    // reports done, violating VISION's "no orphan children" non-negotiable.
    //
    // SIGKILL cannot be trapped/caught by a handler (that's the point of it),
    // so a trap-based marker doesn't work here. Instead: the direct child
    // backgrounds a grandchild (`sleep 30`) and writes its pid to a file.
    // kill_process_tree sends SIGKILL to the whole *process group*
    // (`libc::kill(-pid, ...)`), and a plain, non-interactive `sh -c` script
    // does not put background jobs in their own group, so the grandchild
    // inherits the group `configure_process_group` set up for the direct
    // child. If a regression narrowed the kill back down to just the direct
    // child's pid, the grandchild would survive as a live orphan.
    #[cfg(unix)]
    #[test]
    fn timeout_kills_the_whole_process_group_not_just_the_direct_child() {
        let pidfile = tempfile::NamedTempFile::new().unwrap();
        let pidfile_path = pidfile.path().to_path_buf();

        let mut command = Command::new("sh");
        command.args([
            "-c",
            &format!("sleep 30 & echo $! > {}; wait", pidfile_path.display()),
        ]);
        configure_process_group(&mut command);

        let output = run_with_timeout(command, Duration::from_millis(500)).unwrap();
        assert_eq!(output.status, "timeout");

        // Give the OS a moment to finish delivering the signal.
        std::thread::sleep(Duration::from_millis(200));

        let grandchild_pid: libc::pid_t = std::fs::read_to_string(&pidfile_path)
            .unwrap()
            .trim()
            .parse()
            .expect("grandchild pid file should contain a pid before the timeout fires");
        // SAFETY: signal 0 sends nothing; it only probes whether the pid is
        // alive and signalable, which is safe on any pid value.
        let still_alive = unsafe { libc::kill(grandchild_pid, 0) == 0 };
        assert!(
            !still_alive,
            "grandchild (sleep) pid {grandchild_pid} survived the timeout — \
             kill_process_tree/setpgid did not kill the whole process group, \
             only the direct shell child"
        );
    }

    fn minimal_artifact_json() -> String {
        serde_json::json!({
            "schema_version": "cerberus.review_artifact.v1",
            "artifact_id": "artifact-test",
            "request_id": "req-1",
            "request_digest": "sha256:req",
            "lifecycle_state": "completed",
            "verdict": "PASS",
            "context_capabilities": {
                "diff": true,
                "repo_head": true,
                "repo_base": false,
                "local_runtime": false,
                "remote_runtime": false,
                "external_research": "forbid"
            },
            "summary": {
                "title": "ok",
                "body": "ok",
                "analysis": "",
                "residual_risk": []
            },
            "findings": [],
            "comments": [],
            "suggested_fixes": [],
            "citations": [],
            "receipts": [],
            "run": {
                "engine_version": "test",
                "config_digest": "sha256:test",
                "started_at": "0",
                "finished_at": "1",
                "duration_ms": 1,
                "cost_usd": null,
                "coverage": {
                    "files_reviewed": [],
                    "files_with_findings": []
                }
            },
            "errors": []
        })
        .to_string()
    }

    #[test]
    fn redacts_prompt_file_from_execution_plan_args() {
        let args = vec![
            "@/tmp/private/prompt.md".to_string(),
            "--file".to_string(),
            "/tmp/cerberus-abc/master-prompt.md".to_string(),
            "--file".to_string(),
            "/tmp/cerberus-abc/review-request.json".to_string(),
            "--no-session".to_string(),
        ];
        assert_eq!(
            redact_prompt_path(&args),
            vec![
                "@<prompt-file>".to_string(),
                "--file".to_string(),
                "<prompt-file>".to_string(),
                "--file".to_string(),
                "<request-file>".to_string(),
                "--no-session".to_string()
            ]
        );
    }

    #[test]
    fn opencode_command_uses_file_transport_and_json_events() {
        let substrate = OpenCodeSubstrateConfig {
            binary: "opencode".to_string(),
            attach: Some("http://127.0.0.1:4096".to_string()),
            agent: Some("build".to_string()),
            model: Some("openai/gpt-5.5".to_string()),
        };
        let request = serde_json::from_value::<ReviewRequest>(serde_json::json!({
            "schema_version": "cerberus.review_request.v1",
            "request_id": "req-1",
            "source": {"kind": "fixture", "metadata": {}},
            "change": {
                "title": "change",
                "diff": {"format": "unified", "body": "diff --git a/src/lib.rs b/src/lib.rs\n"},
                "files": []
            },
            "context": {},
            "policy": {}
        }))
        .unwrap();
        let capabilities = ContextCapabilities::from_request(&request);
        let request_digest = request_digest(&request).unwrap();
        let (_binary, args, plan_harness, transport) = command_for_substrate(
            CommandSubstrateConfig::Opencode(&substrate),
            CommandInput {
                cwd: Path::new("/work/repo"),
                prompt_path: Path::new("/tmp/cerberus-test/master-prompt.md"),
                request_path: Path::new("/tmp/cerberus-test/review-request.json"),
                out_path: Path::new("/work/repo/review-artifact.json"),
                request: &request,
                capabilities: &capabilities,
                request_digest: &request_digest,
            },
        )
        .unwrap();
        assert_eq!(plan_harness, "opencode");
        assert_eq!(
            transport,
            "private request file attachment plus argv instructions"
        );
        assert!(args.windows(2).any(|pair| pair == ["--format", "json"]));
        assert!(args
            .iter()
            .any(|arg| arg.contains("Request digest: sha256:")));
        assert!(args.windows(2).any(|pair| pair == ["--dir", "/work/repo"]));
        assert!(args
            .windows(2)
            .any(|pair| pair == ["--file", "/tmp/cerberus-test/review-request.json"]));
        assert!(args.windows(2).any(|pair| pair == ["--agent", "build"]));
        assert!(args
            .windows(2)
            .any(|pair| pair == ["--attach", "http://127.0.0.1:4096"]));
        assert!(
            args.iter()
                .any(|arg| arg.contains("/work/repo/review-artifact.json")),
            "the opencode message must name the artifact out-path"
        );
    }

    fn test_opencode_config() -> OpenCodeSubstrateConfig {
        OpenCodeSubstrateConfig {
            binary: "opencode".to_string(),
            attach: None,
            agent: None,
            model: None,
        }
    }

    #[test]
    fn child_env_uses_only_allowlist() {
        std::env::set_var("CERBERUS_ALLOWED_ENV_TEST", "ok");
        std::env::set_var("GH_TOKEN", "secret");
        let env = allowed_child_env(&["CERBERUS_ALLOWED_ENV_TEST".to_string()]);
        assert_eq!(
            env.get("CERBERUS_ALLOWED_ENV_TEST"),
            Some(&"ok".to_string())
        );
        assert!(!env.contains_key("GH_TOKEN"));
        std::env::remove_var("CERBERUS_ALLOWED_ENV_TEST");
        std::env::remove_var("GH_TOKEN");
    }

    #[test]
    fn nonzero_child_cannot_claim_completed_without_error_receipt() {
        let artifact = serde_json::from_value::<ReviewArtifact>(serde_json::json!({
            "schema_version": "cerberus.review_artifact.v1",
            "artifact_id": "a",
            "request_id": "r",
            "request_digest": "sha256:r",
            "lifecycle_state": "completed",
            "verdict": "PASS",
            "context_capabilities": {
                "diff": true,
                "repo_head": false,
                "repo_base": false,
                "local_runtime": false,
                "remote_runtime": false,
                "external_research": "forbid"
            },
            "summary": {"title": "ok", "body": "ok", "analysis": "", "residual_risk": []},
            "findings": [],
            "comments": [],
            "suggested_fixes": [],
            "citations": [],
            "receipts": [],
            "run": {
                "engine_version": "test",
                "config_digest": "sha256:test",
                "started_at": "0",
                "finished_at": "1",
                "duration_ms": 1,
                "cost_usd": null,
                "coverage": {"files_reviewed": [], "files_with_findings": []}
            },
            "errors": []
        }))
        .unwrap();
        assert!(validate_process_status_matches_artifact("exit status: 1", &artifact).is_err());
    }
}
