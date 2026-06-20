use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use anyhow::{anyhow, Context, Result};
use clap::ValueEnum;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

use crate::digest::request_digest;
use crate::prompt::{build_master_prompt, ARTIFACT_BEGIN, ARTIFACT_END};
use crate::schema::{
    ContextCapabilities, LifecycleState, ReceiptStatus, ReviewArtifact, ReviewRequest,
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
    pub omp_binary: String,
    pub model: Option<String>,
    pub timeout: Duration,
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
        let prompt_path = temp.path().join("master-prompt.md");
        fs::write(&prompt_path, prompt).context("write master prompt")?;
        set_private_permissions(&prompt_path)?;
        let workspace = RunWorkspace::prepare(request, cwd, temp.path())?;

        let (binary, args, plan_harness, prompt_transport) =
            self.command_for_substrate(substrate, workspace.path(), &prompt_path);

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
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .env_clear();
        for (key, value) in allowed_child_env(&request.policy.allowed_env) {
            command.env(key, value);
        }
        command.env("PATH", controlled_path());
        command.env("HOME", temp.path());
        command.env("XDG_CACHE_HOME", temp.path().join("cache"));
        command.env("XDG_CONFIG_HOME", temp.path().join("config"));
        command.env("XDG_DATA_HOME", temp.path().join("data"));
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
        let artifact = extract_marked_artifact(&artifact_text)?;
        validate_process_status_matches_artifact(&output.status, &artifact)?;
        Ok(HarnessRun {
            artifact,
            transcript,
            execution_plan: plan,
        })
    }

    fn command_for_substrate(
        &self,
        substrate: CommandSubstrate,
        cwd: &Path,
        prompt_path: &Path,
    ) -> (String, Vec<String>, &'static str, &'static str) {
        match substrate {
            CommandSubstrate::Opencode => {
                let mut args = vec![
                    "run".to_string(),
                    "Read the attached Cerberus master prompt and follow it exactly.".to_string(),
                    "--format".to_string(),
                    "json".to_string(),
                    "--dir".to_string(),
                    cwd.display().to_string(),
                    "--file".to_string(),
                    prompt_path.display().to_string(),
                ];
                if let Some(model) = &self.model {
                    args.push("--model".to_string());
                    args.push(model.clone());
                }
                if let Some(attach) = &self.opencode_attach {
                    args.push("--attach".to_string());
                    args.push(attach.clone());
                }
                (
                    self.opencode_binary.clone(),
                    args,
                    "opencode",
                    "private prompt file attachment",
                )
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
                    cwd.display().to_string(),
                ];
                if let Some(model) = &self.model {
                    args.push("--model".to_string());
                    args.push(model.clone());
                }
                args.push(format!("@{}", prompt_path.display()));
                (self.omp_binary.clone(), args, "omp", "private prompt file")
            }
        }
    }
}

#[derive(Debug)]
struct RunWorkspace {
    path: PathBuf,
    mode: String,
}

impl RunWorkspace {
    fn prepare(request: &ReviewRequest, fallback_cwd: &Path, temp_root: &Path) -> Result<Self> {
        if let Some(head) = &request.context.workspaces.head {
            return Ok(Self {
                path: PathBuf::from(&head.path),
                mode: "repo_head".to_string(),
            });
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
            })
        } else {
            Ok(Self {
                path: packet,
                mode: "diff_packet".to_string(),
            })
        }
    }

    fn path(&self) -> &Path {
        &self.path
    }

    fn mode(&self) -> &str {
        &self.mode
    }
}

#[derive(Debug, Clone, Copy)]
enum CommandSubstrate {
    Opencode,
    Omp,
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
    let mut child = command.spawn().context("spawn command")?;
    let start = Instant::now();
    loop {
        if let Some(status) = child.try_wait().context("poll command")? {
            let output = child.wait_with_output().context("collect command output")?;
            return Ok(CommandOutput {
                status: status.to_string(),
                stdout: cap_bytes(output.stdout),
                stderr: cap_bytes(output.stderr),
            });
        }
        if start.elapsed() >= timeout {
            kill_process_tree(&mut child);
            let output = child
                .wait_with_output()
                .context("collect killed command output")?;
            return Ok(CommandOutput {
                status: "timeout".to_string(),
                stdout: cap_bytes(output.stdout),
                stderr: cap_bytes(output.stderr),
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

fn cap_bytes(bytes: Vec<u8>) -> Vec<u8> {
    const CAP: usize = 1_000_000;
    if bytes.len() <= CAP {
        bytes
    } else {
        bytes[..CAP].to_vec()
    }
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

fn unix_timestamp_string() -> String {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    format!("{seconds}")
}

pub fn extract_marked_artifact(transcript: &str) -> Result<ReviewArtifact> {
    let begin_count = transcript.matches(ARTIFACT_BEGIN).count();
    let end_count = transcript.matches(ARTIFACT_END).count();
    if begin_count != 1 || end_count != 1 {
        return Err(anyhow!(
            "expected exactly one artifact block, found {begin_count} begin markers and {end_count} end markers"
        ));
    }
    let start = transcript
        .find(ARTIFACT_BEGIN)
        .ok_or_else(|| anyhow!("artifact begin marker missing"))?
        + ARTIFACT_BEGIN.len();
    let end = transcript
        .find(ARTIFACT_END)
        .ok_or_else(|| anyhow!("artifact end marker missing"))?;
    if end <= start {
        return Err(anyhow!("artifact markers are out of order"));
    }
    let json = transcript[start..end].trim();
    serde_json::from_str(json).context("parse ReviewArtifact.v1 block")
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::prompt::{ARTIFACT_BEGIN, ARTIFACT_END};

    #[test]
    fn rejects_missing_marker_block() {
        assert!(extract_marked_artifact("{}").is_err());
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
    fn opencode_json_events_are_reduced_to_text_before_artifact_scan() {
        let artifact = serde_json::json!({
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
        });
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
    fn redacts_prompt_file_from_execution_plan_args() {
        let args = vec![
            "@/tmp/private/prompt.md".to_string(),
            "--file".to_string(),
            "/tmp/cerberus-abc/master-prompt.md".to_string(),
            "--no-session".to_string(),
        ];
        assert_eq!(
            redact_prompt_path(&args),
            vec![
                "@<prompt-file>".to_string(),
                "--file".to_string(),
                "<prompt-file>".to_string(),
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
            omp_binary: "omp".to_string(),
            model: Some("openai/gpt-5.5".to_string()),
            timeout: Duration::from_secs(1),
        };
        let (_binary, args, plan_harness, transport) = harness.command_for_substrate(
            CommandSubstrate::Opencode,
            Path::new("/work/repo"),
            Path::new("/tmp/cerberus-test/master-prompt.md"),
        );
        assert_eq!(plan_harness, "opencode");
        assert_eq!(transport, "private prompt file attachment");
        assert!(args.windows(2).any(|pair| pair == ["--format", "json"]));
        assert!(args
            .iter()
            .any(|arg| arg == "Read the attached Cerberus master prompt and follow it exactly."));
        assert!(args.windows(2).any(|pair| pair == ["--dir", "/work/repo"]));
        assert!(args
            .windows(2)
            .any(|pair| pair == ["--file", "/tmp/cerberus-test/master-prompt.md"]));
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
