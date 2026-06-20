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

use crate::digest::request_digest;
use crate::prompt::{build_master_prompt, build_opencode_message, ARTIFACT_BEGIN, ARTIFACT_END};
use crate::schema::{
    ContextCapabilities, LifecycleState, ReceiptStatus, ReviewArtifact, ReviewRequest,
    REVIEW_ARTIFACT_SCHEMA,
};

#[derive(Debug, Clone, Copy, ValueEnum)]
pub enum HarnessKind {
    Opencode,
    Omp,
    Fixture,
}

#[derive(Debug, Clone)]
pub struct ReviewHarness {
    pub kind: HarnessKind,
    pub fixture_output: Option<PathBuf>,
    pub opencode_binary: String,
    pub opencode_attach: Option<String>,
    pub opencode_agent: Option<String>,
    pub omp_binary: String,
    pub model: Option<String>,
    pub timeout: Duration,
    pub failure_transcript: Option<PathBuf>,
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
}

#[derive(Debug, Clone)]
pub struct HarnessRun {
    pub artifact: ReviewArtifact,
    pub transcript: String,
    pub execution_plan: ExecutionPlan,
}

impl ReviewHarness {
    pub fn run(&self, request: &ReviewRequest, cwd: &Path) -> Result<HarnessRun> {
        match self.kind {
            HarnessKind::Fixture => self.run_fixture(request, cwd),
            HarnessKind::Opencode => self.run_opencode(request, cwd),
            HarnessKind::Omp => self.run_omp(request, cwd),
        }
    }

    fn run_fixture(&self, request: &ReviewRequest, cwd: &Path) -> Result<HarnessRun> {
        let fixture_path = self
            .fixture_output
            .as_ref()
            .ok_or_else(|| anyhow!("--fixture-output is required for fixture harness"))?;
        let raw = fs::read_to_string(fixture_path)
            .with_context(|| format!("read fixture output {}", fixture_path.display()))?;
        let request_digest = request_digest(request)?;
        let capabilities = ContextCapabilities::from_request(request);
        let transcript = apply_fixture_template(&raw, request, &request_digest, &capabilities)?;
        let artifact = extract_marked_artifact(&transcript)?;
        let plan = ExecutionPlan {
            harness: "fixture".to_string(),
            command: fixture_path.display().to_string(),
            args: Vec::new(),
            cwd: cwd.display().to_string(),
            timeout_ms: self.timeout.as_millis() as u64,
            env_allowlist: request.policy.allowed_env.clone(),
            context_capabilities: capabilities,
            prompt_transport: "fixture template".to_string(),
            private_material_in_argv: false,
            workspace_mode: "fixture".to_string(),
        };
        Ok(HarnessRun {
            artifact,
            transcript,
            execution_plan: plan,
        })
    }

    fn run_omp(&self, request: &ReviewRequest, cwd: &Path) -> Result<HarnessRun> {
        self.run_command_substrate(request, cwd, CommandSubstrate::Omp)
    }

    fn run_opencode(&self, request: &ReviewRequest, cwd: &Path) -> Result<HarnessRun> {
        self.run_command_substrate(request, cwd, CommandSubstrate::Opencode)
    }

    fn run_command_substrate(
        &self,
        request: &ReviewRequest,
        cwd: &Path,
        substrate: CommandSubstrate,
    ) -> Result<HarnessRun> {
        let request_digest = request_digest(request)?;
        let capabilities = ContextCapabilities::from_request(request);
        let prompt = build_master_prompt(request, &capabilities, &request_digest)?;
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
        let prompt_path = temp.path().join("master-prompt.md");
        fs::write(&prompt_path, prompt).context("write master prompt")?;
        set_private_permissions(&prompt_path)?;
        let workspace = RunWorkspace::prepare(request, cwd, temp.path())?;
        let request_path = temp.path().join("review-request.json");
        let child_request = request_with_workspace_path(request, workspace.path());
        fs::write(&request_path, serde_json::to_vec_pretty(&child_request)?)
            .context("write review request")?;
        set_private_permissions(&request_path)?;
        if matches!(substrate, CommandSubstrate::Opencode) {
            write_opencode_config(&child_config, workspace.path())?;
        }

        let (binary, args, plan_harness, prompt_transport) = self.command_for_substrate(
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

        let plan = ExecutionPlan {
            harness: plan_harness.to_string(),
            command: binary.clone(),
            args: redact_prompt_path(&args),
            cwd: workspace.path().display().to_string(),
            timeout_ms: self.timeout.as_millis() as u64,
            env_allowlist: request.policy.allowed_env.clone(),
            context_capabilities: capabilities,
            prompt_transport: prompt_transport.to_string(),
            private_material_in_argv: false,
            workspace_mode: workspace.mode().to_string(),
        };

        let start = Instant::now();
        let executable = resolve_executable(&binary).unwrap_or(binary);
        let mut command = Command::new(&executable);
        command
            .args(&args)
            .current_dir(workspace.path())
            .stdin(Stdio::null())
            .env_clear();
        for (key, value) in allowed_child_env(&request.policy.allowed_env) {
            command.env(key, value);
        }
        command.env("PATH", controlled_path());
        command.env("HOME", &child_home);
        command.env("XDG_CACHE_HOME", &child_cache);
        command.env("XDG_CONFIG_HOME", &child_config);
        command.env("XDG_DATA_HOME", &child_data);
        configure_process_group(&mut command);

        let output = run_with_timeout(command, self.timeout)
            .with_context(|| format!("run {plan_harness} harness"))?;
        let elapsed_ms = start.elapsed().as_millis();
        let transcript = format!(
            "exit_status: {}\nelapsed_ms: {}\n\n[stdout]\n{}\n\n[stderr]\n{}",
            output.status,
            elapsed_ms,
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        let artifact_text = artifact_text_for_substrate(substrate, &output.stdout, &transcript);
        let artifact = match extract_marked_artifact(&artifact_text) {
            Ok(artifact) => artifact,
            Err(err) => {
                write_failure_transcript(self.failure_transcript.as_deref(), &transcript)?;
                return Err(err);
            }
        };
        if let Err(err) = validate_process_status_matches_artifact(&output.status, &artifact) {
            write_failure_transcript(self.failure_transcript.as_deref(), &transcript)?;
            return Err(err);
        }
        Ok(HarnessRun {
            artifact,
            transcript,
            execution_plan: plan,
        })
    }

    fn command_for_substrate(
        &self,
        substrate: CommandSubstrate,
        input: CommandInput<'_>,
    ) -> Result<(String, Vec<String>, &'static str, &'static str)> {
        match substrate {
            CommandSubstrate::Opencode => {
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
                if let Some(model) = &self.model {
                    args.push("--model".to_string());
                    args.push(model.clone());
                }
                if let Some(agent) = &self.opencode_agent {
                    args.push("--agent".to_string());
                    args.push(agent.clone());
                }
                if let Some(attach) = &self.opencode_attach {
                    args.push("--attach".to_string());
                    args.push(attach.clone());
                }
                Ok((
                    self.opencode_binary.clone(),
                    args,
                    "opencode",
                    "private request file attachment plus argv instructions",
                ))
            }
            CommandSubstrate::Omp => {
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
                if let Some(model) = &self.model {
                    args.push("--model".to_string());
                    args.push(model.clone());
                }
                args.push(format!("@{}", input.prompt_path.display()));
                Ok((self.omp_binary.clone(), args, "omp", "private prompt file"))
            }
        }
    }
}

fn request_with_workspace_path(request: &ReviewRequest, workspace_path: &Path) -> ReviewRequest {
    let mut child_request = request.clone();
    if let Some(head) = &mut child_request.context.workspaces.head {
        head.path = workspace_path.display().to_string();
    }
    child_request
}

fn write_opencode_config(config_home: &Path, workspace_path: &Path) -> Result<()> {
    let config_dir = config_home.join("opencode");
    fs::create_dir_all(&config_dir)
        .with_context(|| format!("create OpenCode config dir {}", config_dir.display()))?;
    set_private_directory_permissions(&config_dir)?;
    let workspace = workspace_path.display().to_string();
    let workspace_children = format!("{workspace}/**");
    let config = serde_json::json!({
        "$schema": "https://opencode.ai/config.json",
        "permission": {
            "external_directory": {
                workspace.as_str(): "allow",
                workspace_children.as_str(): "allow"
            },
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

#[derive(Debug)]
struct RunWorkspace {
    path: PathBuf,
    mode: String,
    cleanup: Option<WorktreeCleanup>,
}

#[derive(Debug)]
struct WorktreeCleanup {
    source: PathBuf,
    path: PathBuf,
}

impl RunWorkspace {
    fn prepare(request: &ReviewRequest, fallback_cwd: &Path, temp_root: &Path) -> Result<Self> {
        if let Some(head) = &request.context.workspaces.head {
            return Self::prepare_repo_head_workspace(
                Path::new(&head.path),
                head.sha.as_deref(),
                temp_root,
            );
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
            Ok(Self {
                path: fallback_cwd.to_path_buf(),
                mode: "fallback_empty_diff".to_string(),
                cleanup: None,
            })
        } else {
            Ok(Self {
                path: packet,
                mode: "diff_packet".to_string(),
                cleanup: None,
            })
        }
    }

    fn prepare_repo_head_workspace(
        source: &Path,
        sha: Option<&str>,
        temp_root: &Path,
    ) -> Result<Self> {
        let sha = sha.ok_or_else(|| {
            anyhow!(
                "repo_head workspace {} requires a sha for disposable review checkout",
                source.display()
            )
        })?;
        let worktree = temp_root.join("repo-head");
        let output = Command::new("git")
            .arg("-C")
            .arg(source)
            .args(["worktree", "add", "--detach"])
            .arg(&worktree)
            .arg(sha)
            .output()
            .with_context(|| {
                format!(
                    "create disposable review worktree from {}",
                    source.display()
                )
            })?;
        if !output.status.success() {
            return Err(anyhow!(
                "create disposable review worktree from {} failed: {}",
                source.display(),
                String::from_utf8_lossy(&output.stderr)
            ));
        }
        Ok(Self {
            path: worktree.clone(),
            mode: "repo_head_worktree".to_string(),
            cleanup: Some(WorktreeCleanup {
                source: source.to_path_buf(),
                path: worktree,
            }),
        })
    }

    fn path(&self) -> &Path {
        &self.path
    }

    fn mode(&self) -> &str {
        &self.mode
    }
}

impl Drop for RunWorkspace {
    fn drop(&mut self) {
        if let Some(cleanup) = &self.cleanup {
            let _ = Command::new("git")
                .arg("-C")
                .arg(&cleanup.source)
                .args(["worktree", "remove", "--force"])
                .arg(&cleanup.path)
                .output();
        }
    }
}

#[derive(Debug, Clone, Copy)]
enum CommandSubstrate {
    Opencode,
    Omp,
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

fn controlled_path() -> String {
    let mut paths = vec![
        "/usr/bin".to_string(),
        "/bin".to_string(),
        "/usr/sbin".to_string(),
        "/sbin".to_string(),
    ];
    for candidate in ["/opt/homebrew/bin", "/usr/local/bin"] {
        if Path::new(candidate).is_dir() {
            paths.push(candidate.to_string());
        }
    }
    if let Some(home) = std::env::var_os("HOME").map(PathBuf::from) {
        for relative in [".bun/bin", ".opencode/bin", ".local/bin"] {
            let candidate = home.join(relative);
            if candidate.is_dir() {
                paths.push(candidate.display().to_string());
            }
        }
    }
    paths.join(":")
}

fn resolve_executable(binary: &str) -> Option<String> {
    if binary.contains('/') {
        return Some(binary.to_string());
    }
    let paths = std::env::var_os("PATH")?;
    std::env::split_paths(&paths)
        .map(|path| path.join(binary))
        .find(|path| path.is_file())
        .map(|path| path.display().to_string())
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
    substrate: CommandSubstrate,
    stdout: &[u8],
    transcript: &str,
) -> String {
    match substrate {
        CommandSubstrate::Opencode => extract_opencode_text_events(stdout)
            .filter(|text| !text.trim().is_empty())
            .unwrap_or_else(|| transcript.to_string()),
        CommandSubstrate::Omp => transcript.to_string(),
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
    let marked_json = extract_json_between_markers(transcript, ARTIFACT_BEGIN, ARTIFACT_END)
        .or_else(|| extract_xml_wrapped_artifact_json(transcript))
        .or_else(|| extract_unmarked_artifact_json(transcript));
    let Some(json) = marked_json else {
        let begin_count = transcript.matches(ARTIFACT_BEGIN).count();
        let end_count = transcript.matches(ARTIFACT_END).count();
        let xml_begin_count = transcript.matches("<CERBERUS_REVIEW_ARTIFACT_V1>").count();
        let xml_end_count = transcript.matches("</CERBERUS_REVIEW_ARTIFACT_V1>").count();
        return Err(anyhow!(
            "expected exactly one artifact block, found {begin_count} begin markers, {end_count} end markers, {xml_begin_count} xml begin markers, and {xml_end_count} xml end markers"
        ));
    };
    serde_json::from_str(&json).context("parse ReviewArtifact.v1 block")
}

fn extract_json_between_markers(transcript: &str, begin: &str, end: &str) -> Option<String> {
    let start = transcript.find(begin)? + begin.len();
    let remainder = &transcript[start..];
    let finish = remainder.find(end)?;
    let candidate = strip_markdown_json_fence(&remainder[..finish]);
    if candidate.is_empty() {
        None
    } else {
        Some(candidate.to_string())
    }
}

fn extract_xml_wrapped_artifact_json(transcript: &str) -> Option<String> {
    let candidate = extract_json_between_markers(
        transcript,
        "<CERBERUS_REVIEW_ARTIFACT_V1>",
        "</CERBERUS_REVIEW_ARTIFACT_V1>",
    )?;
    let parsed = serde_json::from_str::<ReviewArtifact>(&candidate).ok()?;
    if parsed.schema_version == REVIEW_ARTIFACT_SCHEMA {
        Some(candidate)
    } else {
        None
    }
}

fn extract_unmarked_artifact_json(transcript: &str) -> Option<String> {
    let schema_index = transcript.find(REVIEW_ARTIFACT_SCHEMA)?;
    let mut starts: Vec<usize> = transcript[..schema_index]
        .match_indices('{')
        .map(|(index, _)| index)
        .collect();
    starts.reverse();
    for start in starts {
        let slice = &transcript[start..];
        let mut deserializer = serde_json::Deserializer::from_str(slice);
        let Ok(value) = Value::deserialize(&mut deserializer) else {
            continue;
        };
        if value.get("schema_version").and_then(Value::as_str) == Some(REVIEW_ARTIFACT_SCHEMA) {
            return Some(value.to_string());
        }
    }
    None
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

        write_opencode_config(temp.path(), &workspace).unwrap();

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
    fn rejects_multiple_marker_blocks() {
        let transcript = format!(
            "{begin}{{}}{end}\n{begin}{{}}{end}",
            begin = ARTIFACT_BEGIN,
            end = ARTIFACT_END
        );
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
        let text =
            artifact_text_for_substrate(CommandSubstrate::Opencode, stdout.as_bytes(), "fallback");
        assert!(text.contains(ARTIFACT_BEGIN));
        assert!(!text.contains("\"type\":\"text\""));
        assert_eq!(extract_marked_artifact(&text).unwrap().request_id, "req-1");
    }

    #[test]
    fn opencode_artifact_scan_falls_back_to_transcript_without_text_events() {
        let stdout = b"{\"type\":\"start\"}\n{\"type\":\"end\"}\n";
        let transcript = format!(
            "{begin}\n{artifact}\n{end}",
            begin = ARTIFACT_BEGIN,
            artifact = minimal_artifact_json(),
            end = ARTIFACT_END
        );

        let text = artifact_text_for_substrate(CommandSubstrate::Opencode, stdout, &transcript);

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
        let text = artifact_text_for_substrate(CommandSubstrate::Opencode, &capped, "fallback");
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
        let harness = ReviewHarness {
            kind: HarnessKind::Opencode,
            fixture_output: None,
            opencode_binary: "opencode".to_string(),
            opencode_attach: Some("http://127.0.0.1:4096".to_string()),
            opencode_agent: Some("build".to_string()),
            omp_binary: "omp".to_string(),
            model: Some("openai/gpt-5.5".to_string()),
            timeout: Duration::from_secs(1),
            failure_transcript: None,
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
        let (_binary, args, plan_harness, transport) = harness
            .command_for_substrate(
                CommandSubstrate::Opencode,
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
