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
use crate::prompt::{build_master_prompt, build_opencode_message, ARTIFACT_BEGIN, ARTIFACT_END};
use crate::schema::{
    ContextArtifact, ContextCapabilities, LifecycleState, ReceiptStatus, ReviewArtifact,
    ReviewRequest, ReviewTelemetry, RuntimeTarget, REVIEW_ARTIFACT_SCHEMA,
};
use crate::telemetry::{omp_telemetry, opencode_telemetry};

#[derive(Debug, Clone, Copy, ValueEnum)]
pub enum HarnessKind {
    Opencode,
    Omp,
    Fixture,
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
    cwd: &Path,
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
    let workspace = RunWorkspace::prepare(request, cwd, temp.path())?;
    let mut child_request = request_with_workspace_paths(request, &workspace);
    let runtime_receipts =
        run_local_runtime_probes(&mut child_request, &workspace, temp.path(), timeout)?;
    let fixture_transcript = apply_fixture_template(&raw, request, &request_digest, &capabilities)?;
    let transcript = format!(
        "{}{}",
        runtime_probe_transcript(&runtime_receipts),
        fixture_transcript
    );
    let artifact = extract_marked_artifact(&transcript)?;
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
    cwd: &Path,
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
    let workspace = RunWorkspace::prepare(request, cwd, temp.path())?;
    let mut child_request = request_with_workspace_paths(request, &workspace);
    let runtime_receipts =
        run_local_runtime_probes(&mut child_request, &workspace, temp.path(), timeout)?;
    let prompt = build_master_prompt(&child_request, &capabilities, &request_digest)?;
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

    let start = Instant::now();
    let mut command = Command::new(&executable);
    command
        .args(&args)
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

    let output = run_with_timeout(command, timeout)
        .with_context(|| format!("run {plan_harness} harness"))?;
    let elapsed_ms = start.elapsed().as_millis();
    let transcript = format!(
        "{}exit_status: {}\nelapsed_ms: {}\n\n[stdout]\n{}\n\n[stderr]\n{}",
        runtime_probe_transcript(&runtime_receipts),
        output.status,
        elapsed_ms,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let artifact_text = artifact_text_for_substrate(substrate, &output.stdout, &transcript);
    let telemetry = telemetry_for_substrate(substrate, &output.stdout);
    let artifact = match extract_marked_artifact(&artifact_text) {
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

fn command_for_substrate(
    substrate: CommandSubstrateConfig<'_>,
    input: CommandInput<'_>,
) -> Result<(String, Vec<String>, &'static str, &'static str)> {
    match substrate {
        CommandSubstrateConfig::Opencode(config) => {
            let message =
                build_opencode_message(input.request, input.capabilities, input.request_digest)
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
            if let Some(model) = &config.model {
                args.push("--model".to_string());
                args.push(model.clone());
            }
            if let Some(agent) = &config.agent {
                args.push("--agent".to_string());
                args.push(agent.clone());
            }
            if let Some(attach) = &config.attach {
                args.push("--attach".to_string());
                args.push(attach.clone());
            }
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
    let config = serde_json::json!({
        "$schema": "https://opencode.ai/config.json",
        "permission": {
            "external_directory": external_directory,
            "edit": {
                "*": "deny"
            }
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
    fn prepare(request: &ReviewRequest, fallback_cwd: &Path, temp_root: &Path) -> Result<Self> {
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

        if request.change.diff.body.trim().is_empty() {
            Ok(Self::with_packet_or_fallback(
                fallback_cwd.to_path_buf(),
                "fallback_empty_diff",
            ))
        } else {
            Ok(Self::with_packet_or_fallback(packet, "diff_packet"))
        }
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

    fn with_packet_or_fallback(path: PathBuf, mode: &str) -> Self {
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
    request: &'a ReviewRequest,
    capabilities: &'a ContextCapabilities,
    request_digest: &'a str,
}

#[derive(Debug)]
struct CommandOutput {
    status: String,
    stdout: Vec<u8>,
    stderr: Vec<u8>,
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
            });
        }
        if start.elapsed() >= timeout {
            kill_process_tree(&mut child);
            child.wait().context("collect killed command status")?;
            return Ok(CommandOutput {
                status: "timeout".to_string(),
                stdout: read_capped_file(stdout_capture.path()).context("read stdout capture")?,
                stderr: read_capped_file(stderr_capture.path()).context("read stderr capture")?,
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

#[cfg(test)]
fn cap_bytes(bytes: Vec<u8>) -> Vec<u8> {
    if bytes.len() <= OUTPUT_CAPTURE_CAP {
        return bytes;
    }
    let available = OUTPUT_CAPTURE_CAP.saturating_sub(OUTPUT_TRUNCATION_MARKER.len());
    if available == 0 {
        bytes[bytes.len() - OUTPUT_CAPTURE_CAP..].to_vec()
    } else {
        let head_len = available / 2;
        let tail_len = available - head_len;
        let mut capped = Vec::with_capacity(OUTPUT_CAPTURE_CAP);
        capped.extend_from_slice(&bytes[..head_len]);
        capped.extend_from_slice(OUTPUT_TRUNCATION_MARKER);
        capped.extend_from_slice(&bytes[bytes.len() - tail_len..]);
        capped
    }
}

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

fn artifact_text_for_substrate(
    substrate: CommandSubstrateConfig<'_>,
    stdout: &[u8],
    transcript: &str,
) -> String {
    match substrate {
        CommandSubstrateConfig::Opencode(_) => extract_opencode_text_events(stdout)
            .filter(|text| !text.trim().is_empty())
            .unwrap_or_else(|| transcript.to_string()),
        CommandSubstrateConfig::Omp(_) => transcript.to_string(),
    }
}

fn extract_opencode_text_events(stdout: &[u8]) -> Option<String> {
    let raw = String::from_utf8_lossy(stdout);
    let mut text = String::new();
    for line in raw.lines() {
        let Ok(value) = serde_json::from_str::<Value>(line) else {
            continue;
        };
        if value.get("type").and_then(Value::as_str) != Some("text") {
            continue;
        }
        if let Some(part_text) = value.pointer("/part/text").and_then(Value::as_str) {
            text.push_str(part_text);
            text.push('\n');
        }
    }
    if text.trim().is_empty() {
        None
    } else {
        Some(text)
    }
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

pub fn extract_marked_artifact(transcript: &str) -> Result<ReviewArtifact> {
    let mut candidates = Vec::new();
    let marker_candidates =
        extract_json_between_markers(transcript, ARTIFACT_BEGIN, ARTIFACT_END, "marker");
    let xml_candidates = extract_json_between_markers(
        transcript,
        "<CERBERUS_REVIEW_ARTIFACT_V1>",
        "</CERBERUS_REVIEW_ARTIFACT_V1>",
        "xml",
    );
    let explicit_spans = marker_candidates
        .iter()
        .chain(xml_candidates.iter())
        .map(|candidate| (candidate.start, candidate.end))
        .collect::<Vec<_>>();
    let raw_candidates = extract_unmarked_artifact_json(transcript, &explicit_spans);
    let marker_count = marker_candidates.len();
    let xml_count = xml_candidates.len();
    let raw_count = raw_candidates.len();
    candidates.extend(marker_candidates);
    candidates.extend(xml_candidates);
    candidates.extend(raw_candidates);

    if candidates.len() != 1 {
        let begin_count = transcript.matches(ARTIFACT_BEGIN).count();
        let end_count = transcript.matches(ARTIFACT_END).count();
        let xml_begin_count = transcript.matches("<CERBERUS_REVIEW_ARTIFACT_V1>").count();
        let xml_end_count = transcript.matches("</CERBERUS_REVIEW_ARTIFACT_V1>").count();
        return Err(anyhow!(
            "expected exactly one ReviewArtifact.v1 candidate, found {marker_count} marker, {xml_count} xml, and {raw_count} raw candidates ({begin_count} begin markers, {end_count} end markers, {xml_begin_count} xml begin markers, {xml_end_count} xml end markers)"
        ));
    }
    serde_json::from_str(&candidates.remove(0).json).context("parse ReviewArtifact.v1 block")
}

#[derive(Debug)]
struct ArtifactCandidate {
    json: String,
    start: usize,
    end: usize,
}

fn extract_json_between_markers(
    transcript: &str,
    begin: &str,
    end: &str,
    _format: &'static str,
) -> Vec<ArtifactCandidate> {
    let mut candidates = Vec::new();
    let mut cursor = 0;
    while let Some(relative_start) = transcript[cursor..].find(begin) {
        let block_start = cursor + relative_start;
        let content_start = block_start + begin.len();
        let Some(relative_end) = transcript[content_start..].find(end) else {
            break;
        };
        let content_end = content_start + relative_end;
        let block_end = content_end + end.len();
        let candidate = strip_markdown_json_fence(&transcript[content_start..content_end]);
        if !candidate.is_empty() {
            candidates.push(ArtifactCandidate {
                json: candidate.to_string(),
                start: block_start,
                end: block_end,
            });
        }
        cursor = block_end;
    }
    candidates
}

fn extract_unmarked_artifact_json(
    transcript: &str,
    excluded_spans: &[(usize, usize)],
) -> Vec<ArtifactCandidate> {
    let mut candidates = Vec::new();
    for (start, _) in transcript.match_indices('{') {
        if excluded_spans
            .iter()
            .any(|(span_start, span_end)| start >= *span_start && start < *span_end)
        {
            continue;
        }
        let slice = &transcript[start..];
        let mut deserializer = serde_json::Deserializer::from_str(slice);
        let Ok(value) = Value::deserialize(&mut deserializer) else {
            continue;
        };
        if value.get("schema_version").and_then(Value::as_str) == Some(REVIEW_ARTIFACT_SCHEMA) {
            candidates.push(ArtifactCandidate {
                json: value.to_string(),
                start,
                end: start,
            });
        }
    }
    candidates
}

fn strip_markdown_json_fence(raw: &str) -> &str {
    let trimmed = raw.trim();
    let Some(without_prefix) = trimmed.strip_prefix("```") else {
        return trimmed;
    };
    let without_language = without_prefix
        .strip_prefix("json")
        .or_else(|| without_prefix.strip_prefix("JSON"))
        .unwrap_or(without_prefix)
        .trim_start_matches([' ', '\t', '\r', '\n']);
    without_language
        .strip_suffix("```")
        .unwrap_or(without_language)
        .trim()
}

#[cfg(unix)]
fn set_private_permissions(path: &Path) -> Result<()> {
    use std::os::unix::fs::PermissionsExt;
    let mut permissions = fs::metadata(path)?.permissions();
    permissions.set_mode(0o600);
    fs::set_permissions(path, permissions)?;
    Ok(())
}

#[cfg(not(unix))]
fn set_private_permissions(_path: &Path) -> Result<()> {
    Ok(())
}

#[cfg(unix)]
fn set_private_directory_permissions(path: &Path) -> Result<()> {
    use std::os::unix::fs::PermissionsExt;
    let mut permissions = fs::metadata(path)?.permissions();
    permissions.set_mode(0o700);
    fs::set_permissions(path, permissions)?;
    Ok(())
}

#[cfg(not(unix))]
fn set_private_directory_permissions(_path: &Path) -> Result<()> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::prompt::{ARTIFACT_BEGIN, ARTIFACT_END};
    #[cfg(unix)]
    use std::os::unix::fs::PermissionsExt;

    #[test]
    fn rejects_missing_marker_block() {
        assert!(extract_marked_artifact("{}").is_err());
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
    fn opencode_config_allows_only_review_workspace_external_directory() {
        let temp = tempfile::tempdir().unwrap();
        let workspace = temp.path().join("repo-head");
        fs::create_dir(&workspace).unwrap();

        write_opencode_config(temp.path(), std::slice::from_ref(&workspace)).unwrap();

        let config_path = temp.path().join("opencode/opencode.json");
        let config: Value =
            serde_json::from_str(&fs::read_to_string(config_path).unwrap()).unwrap();
        assert_eq!(
            config.pointer("/permission/edit/*").and_then(Value::as_str),
            Some("deny")
        );
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
    fn rejects_multiple_marker_blocks() {
        let artifact = minimal_artifact_json();
        let transcript = format!(
            "{begin}{artifact}{end}\n{begin}{artifact}{end}",
            begin = ARTIFACT_BEGIN,
            artifact = artifact,
            end = ARTIFACT_END
        );
        assert!(extract_marked_artifact(&transcript).is_err());
    }

    #[test]
    fn rejects_marker_and_xml_artifact_candidates_together() {
        let artifact = minimal_artifact_json();
        let transcript = format!(
            "{begin}{artifact}{end}\n<CERBERUS_REVIEW_ARTIFACT_V1>{artifact}</CERBERUS_REVIEW_ARTIFACT_V1>",
            begin = ARTIFACT_BEGIN,
            artifact = artifact,
            end = ARTIFACT_END
        );
        assert!(extract_marked_artifact(&transcript).is_err());
    }

    #[test]
    fn rejects_marker_and_raw_artifact_candidates_together() {
        let artifact = minimal_artifact_json();
        let transcript = format!(
            "{begin}{artifact}{end}\n{artifact}",
            begin = ARTIFACT_BEGIN,
            artifact = artifact,
            end = ARTIFACT_END
        );
        assert!(extract_marked_artifact(&transcript).is_err());
    }

    #[test]
    fn rejects_multiple_xml_artifact_candidates() {
        let artifact = minimal_artifact_json();
        let transcript = format!(
            "<CERBERUS_REVIEW_ARTIFACT_V1>{artifact}</CERBERUS_REVIEW_ARTIFACT_V1>\n<CERBERUS_REVIEW_ARTIFACT_V1>{artifact}</CERBERUS_REVIEW_ARTIFACT_V1>",
            artifact = artifact
        );
        assert!(extract_marked_artifact(&transcript).is_err());
    }

    #[test]
    fn rejects_xml_and_raw_artifact_candidates_together() {
        let artifact = minimal_artifact_json();
        let transcript = format!(
            "<CERBERUS_REVIEW_ARTIFACT_V1>{artifact}</CERBERUS_REVIEW_ARTIFACT_V1>\n{artifact}",
            artifact = artifact
        );
        assert!(extract_marked_artifact(&transcript).is_err());
    }

    #[test]
    fn rejects_multiple_raw_artifact_candidates() {
        let artifact = minimal_artifact_json();
        let transcript = format!("first\n{artifact}\nsecond\n{artifact}", artifact = artifact);
        assert!(extract_marked_artifact(&transcript).is_err());
    }

    #[test]
    fn extracts_artifact_inside_markdown_json_fence() {
        let transcript = format!(
            "{begin}\n```json\n{json}\n```\n{end}",
            begin = ARTIFACT_BEGIN,
            json = minimal_artifact_json(),
            end = ARTIFACT_END
        );
        assert_eq!(
            extract_marked_artifact(&transcript).unwrap().request_id,
            "req-1"
        );
    }

    #[test]
    fn extracts_artifact_from_opencode_xml_wrapper_variant() {
        let transcript = format!(
            "```json\n<CERBERUS_REVIEW_ARTIFACT_V1>\n{json}\n</CERBERUS_REVIEW_ARTIFACT_V1>\n```",
            json = minimal_artifact_json()
        );
        assert_eq!(
            extract_marked_artifact(&transcript).unwrap().request_id,
            "req-1"
        );
    }

    #[test]
    fn extracts_unmarked_review_artifact_json_from_prose() {
        let transcript = format!(
            "Here is the review.\n```json\n{json}\n```\nDone.",
            json = minimal_artifact_json()
        );
        assert_eq!(
            extract_marked_artifact(&transcript).unwrap().request_id,
            "req-1"
        );
    }

    #[test]
    fn extracts_raw_review_artifact_json_after_prose_prefix() {
        let transcript = format!(
            "I have enough evidence.\n\n{json}",
            json = minimal_artifact_json()
        );

        assert_eq!(
            extract_marked_artifact(&transcript).unwrap().request_id,
            "req-1"
        );
    }

    #[test]
    fn opencode_json_events_are_reduced_to_text_before_artifact_scan() {
        let artifact = minimal_artifact_json();
        let event = serde_json::json!({
            "type": "text",
            "part": {
                "text": format!(
                    "{begin}\n{artifact}\n{end}",
                    begin = ARTIFACT_BEGIN,
                    artifact = artifact,
                    end = ARTIFACT_END
                )
            }
        });
        let stdout = format!(
            "{{\"type\":\"start\"}}\n{}\nnot json\n",
            serde_json::to_string(&event).unwrap()
        );
        let config = test_opencode_config();
        let text = artifact_text_for_substrate(
            CommandSubstrateConfig::Opencode(&config),
            stdout.as_bytes(),
            "fallback",
        );
        assert!(text.contains(ARTIFACT_BEGIN));
        assert!(!text.contains("\"type\":\"text\""));
        assert_eq!(extract_marked_artifact(&text).unwrap().request_id, "req-1");
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

    #[test]
    fn opencode_artifact_scan_falls_back_to_transcript_without_text_events() {
        let stdout = b"{\"type\":\"start\"}\n{\"type\":\"end\"}\n";
        let transcript = format!(
            "{begin}\n{artifact}\n{end}",
            begin = ARTIFACT_BEGIN,
            artifact = minimal_artifact_json(),
            end = ARTIFACT_END
        );

        let config = test_opencode_config();
        let text = artifact_text_for_substrate(
            CommandSubstrateConfig::Opencode(&config),
            stdout,
            &transcript,
        );

        assert_eq!(text, transcript);
        assert_eq!(extract_marked_artifact(&text).unwrap().request_id, "req-1");
    }

    #[test]
    fn opencode_artifact_survives_large_stdout_tail_capture() {
        let artifact = minimal_artifact_json();
        let event = serde_json::json!({
            "type": "text",
            "part": {
                "text": artifact
            }
        });
        let mut stdout = vec![b'a'; OUTPUT_CAPTURE_CAP + 250_000];
        stdout.extend_from_slice(b"\n");
        stdout.extend_from_slice(serde_json::to_string(&event).unwrap().as_bytes());
        stdout.extend_from_slice(b"\n");

        let capped = cap_bytes(stdout);
        assert!(String::from_utf8_lossy(&capped).contains("cerberus truncated middle"));
        let config = test_opencode_config();
        let text = artifact_text_for_substrate(
            CommandSubstrateConfig::Opencode(&config),
            &capped,
            "fallback",
        );
        assert_eq!(extract_marked_artifact(&text).unwrap().request_id, "req-1");
    }

    #[cfg(unix)]
    #[test]
    fn run_with_timeout_captures_stdout_larger_than_pipe_buffer() {
        let mut command = Command::new("sh");
        command.args(["-c", "yes x | head -c 200000"]);

        let output = run_with_timeout(command, Duration::from_secs(5)).unwrap();

        assert!(output.status.contains('0'));
        assert_eq!(output.stdout.len(), 200000);
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
