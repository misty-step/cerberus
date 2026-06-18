use cerberus_core::{HarnessRuntimeError, ReviewHarness};
use cerberus_schema::{PeerHarnessCommandProfile, ReviewRequest, ReviewerArtifact, ReviewerConfig};
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::atomic::{AtomicU64, Ordering},
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

#[cfg(unix)]
use std::os::unix::{fs::PermissionsExt, process::CommandExt};

static NEXT_TEMP_ID: AtomicU64 = AtomicU64::new(0);
const DIAGNOSTIC_MAX_BYTES: u64 = 4096;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CommandHarnessInput {
    pub reviewer: ReviewerConfig,
    pub request: ReviewRequest,
}

#[derive(Debug, Clone)]
pub struct CommandHarness {
    command: String,
    args: Vec<String>,
    timeout: Duration,
}

impl CommandHarness {
    pub fn new(command: impl Into<String>) -> Self {
        Self {
            command: command.into(),
            args: vec![],
            timeout: Duration::from_secs(120),
        }
    }

    pub fn arg(mut self, arg: impl Into<String>) -> Self {
        self.args.push(arg.into());
        self
    }

    pub fn args(mut self, args: impl IntoIterator<Item = impl Into<String>>) -> Self {
        self.args.extend(args.into_iter().map(Into::into));
        self
    }

    pub fn timeout(mut self, timeout: Duration) -> Self {
        self.timeout = timeout;
        self
    }

    pub fn command(&self) -> &str {
        &self.command
    }

    pub fn configured_args(&self) -> &[String] {
        &self.args
    }

    pub fn configured_timeout(&self) -> Duration {
        self.timeout
    }
}

impl TryFrom<&PeerHarnessCommandProfile> for CommandHarness {
    type Error = cerberus_schema::SchemaError;

    fn try_from(profile: &PeerHarnessCommandProfile) -> Result<Self, Self::Error> {
        profile.validate()?;
        Ok(CommandHarness::new(profile.command.clone())
            .args(profile.args.clone())
            .timeout(Duration::from_millis(profile.timeout_ms)))
    }
}

impl ReviewHarness for CommandHarness {
    fn review(
        &self,
        reviewer: &ReviewerConfig,
        request: &ReviewRequest,
    ) -> Result<ReviewerArtifact, HarnessRuntimeError> {
        let files = CommandHarnessFiles::create(&reviewer.id)?;
        let input = CommandHarnessInput {
            reviewer: reviewer.clone(),
            request: request.clone(),
        };
        let input_json = serde_json::to_string_pretty(&input).map_err(|error| {
            HarnessRuntimeError::Failed(format!("input serialization failed: {error}"))
        })?;
        write_private_file(&files.input, &format!("{input_json}\n")).map_err(|error| {
            HarnessRuntimeError::Failed(format!(
                "failed to write command harness input {}: {error}",
                files.input.display()
            ))
        })?;

        create_private_file(&files.output).map_err(|error| {
            HarnessRuntimeError::Failed(format!(
                "failed to create command harness output {}: {error}",
                files.output.display()
            ))
        })?;
        let stdout = create_private_file(&files.stdout).map_err(|error| {
            HarnessRuntimeError::Failed(format!(
                "failed to create command harness stdout {}: {error}",
                files.stdout.display()
            ))
        })?;
        let stderr = create_private_file(&files.stderr).map_err(|error| {
            HarnessRuntimeError::Failed(format!(
                "failed to create command harness stderr {}: {error}",
                files.stderr.display()
            ))
        })?;
        let mut command = Command::new(&self.command);
        command
            .args(&self.args)
            .arg("--input")
            .arg(&files.input)
            .arg("--output")
            .arg(&files.output)
            .stdout(Stdio::from(stdout))
            .stderr(Stdio::from(stderr));
        start_new_process_group(&mut command);
        let mut child = command.spawn().map_err(|error| {
            HarnessRuntimeError::Failed(format!("failed to launch {:?}: {error}", self.command))
        })?;

        let deadline = Instant::now() + self.timeout;
        let status = loop {
            match child.try_wait() {
                Ok(Some(status)) => break status,
                Ok(None) if Instant::now() >= deadline => {
                    terminate_process_group(&mut child);
                    return Err(HarnessRuntimeError::Timeout(format!(
                        "{:?} exceeded {} ms",
                        self.command,
                        self.timeout.as_millis()
                    )));
                }
                Ok(None) => thread::sleep(Duration::from_millis(10)),
                Err(error) => {
                    return Err(HarnessRuntimeError::Failed(format!(
                        "failed while waiting for {:?}: {error}",
                        self.command
                    )));
                }
            }
        };

        let stderr = read_bounded_lossy(&files.stderr, DIAGNOSTIC_MAX_BYTES);
        if !status.success() {
            return Err(HarnessRuntimeError::Failed(format!(
                "{:?} exited with {status}: {}",
                self.command,
                stderr.trim()
            )));
        }

        let raw_artifact = fs::read_to_string(&files.output).map_err(|error| {
            HarnessRuntimeError::Failed(format!(
                "failed to read command harness output {}: {error}",
                files.output.display()
            ))
        })?;
        serde_json::from_str(&raw_artifact).map_err(|error| {
            HarnessRuntimeError::Failed(format!(
                "failed to parse command harness output {}: {error}",
                files.output.display()
            ))
        })
    }
}

#[derive(Debug)]
struct CommandHarnessFiles {
    root: PathBuf,
    input: PathBuf,
    output: PathBuf,
    stdout: PathBuf,
    stderr: PathBuf,
}

impl Drop for CommandHarnessFiles {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

impl CommandHarnessFiles {
    fn create(reviewer_id: &str) -> Result<Self, HarnessRuntimeError> {
        let root = std::env::temp_dir().join(format!(
            "cerberus-command-harness-{}-{}",
            std::process::id(),
            unique_suffix()
        ));
        fs::create_dir(&root).map_err(|error| {
            HarnessRuntimeError::Failed(format!(
                "failed to create command harness temp dir {}: {error}",
                root.display()
            ))
        })?;
        if let Err(error) = set_private_dir_permissions(&root) {
            let _ = fs::remove_dir_all(&root);
            return Err(HarnessRuntimeError::Failed(format!(
                "failed to restrict command harness temp dir {}: {error}",
                root.display()
            )));
        }
        let stem = sanitize(reviewer_id);
        Ok(Self {
            root: root.clone(),
            input: root.join(format!("{stem}.input.json")),
            output: root.join(format!("{stem}.output.json")),
            stdout: root.join(format!("{stem}.stdout.txt")),
            stderr: root.join(format!("{stem}.stderr.txt")),
        })
    }
}

fn create_private_file(path: &Path) -> std::io::Result<File> {
    let file = OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .open(path)?;
    set_private_file_permissions(path)?;
    Ok(file)
}

fn write_private_file(path: &Path, contents: &str) -> std::io::Result<()> {
    let mut file = create_private_file(path)?;
    file.write_all(contents.as_bytes())
}

fn set_private_dir_permissions(path: &Path) -> std::io::Result<()> {
    #[cfg(unix)]
    {
        fs::set_permissions(path, fs::Permissions::from_mode(0o700))?;
    }
    Ok(())
}

fn set_private_file_permissions(path: &Path) -> std::io::Result<()> {
    #[cfg(unix)]
    {
        fs::set_permissions(path, fs::Permissions::from_mode(0o600))?;
    }
    Ok(())
}

fn start_new_process_group(command: &mut Command) {
    #[cfg(unix)]
    {
        command.process_group(0);
    }
}

fn terminate_process_group(child: &mut Child) {
    #[cfg(unix)]
    {
        let pgid = -(child.id() as libc::pid_t);
        unsafe {
            libc::kill(pgid, libc::SIGTERM);
        }
        thread::sleep(Duration::from_millis(50));
        unsafe {
            libc::kill(pgid, libc::SIGKILL);
        }
        let _ = child.wait();
        return;
    }

    #[cfg(not(unix))]
    {
        let _ = child.kill();
        let _ = child.wait();
    }
}

fn unique_suffix() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    let sequence = NEXT_TEMP_ID.fetch_add(1, Ordering::Relaxed);
    format!("{nanos}-{sequence}")
}

fn sanitize(value: &str) -> String {
    value
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || character == '-' || character == '_' {
                character
            } else {
                '_'
            }
        })
        .collect()
}

fn read_bounded_lossy(path: &Path, max_bytes: u64) -> String {
    let mut file = match File::open(path) {
        Ok(file) => file,
        Err(_) => return String::new(),
    };
    let mut bytes = Vec::new();
    if Read::by_ref(&mut file)
        .take(max_bytes)
        .read_to_end(&mut bytes)
        .is_err()
    {
        return String::new();
    }
    let mut output = String::from_utf8_lossy(&bytes).into_owned();
    if fs::metadata(path)
        .map(|metadata| metadata.len() > max_bytes)
        .unwrap_or(false)
    {
        output.push_str("...[truncated]");
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;
    use cerberus_core::review_with_harness;
    use cerberus_schema::{
        Change, ChangedFile, FileStatus, ReviewConfig, ReviewContext, ReviewRequest, ReviewSource,
        ReviewerConfig, ReviewerStatus, Verdict, REVIEW_CONFIG_VERSION, REVIEW_REQUEST_VERSION,
    };
    use std::{collections::BTreeMap, time::Duration};

    #[test]
    fn command_harness_runs_fixture_command_and_feeds_core_aggregation() {
        let request = request();
        let config = config();
        let harness = fixture_harness("success");

        let artifact =
            review_with_harness(&request, &config, &harness).expect("command harness review works");

        assert_eq!(artifact.verdict, Verdict::Fail);
        assert!(!artifact.degraded);
        assert_eq!(artifact.findings.len(), 1);
        assert_eq!(artifact.findings[0].reviewer_id, "command-reviewer");
        artifact.validate().expect("run artifact validates");
    }

    #[test]
    fn peer_harness_profile_builds_command_harness() {
        let profile = fixture_peer_profile();
        let harness = CommandHarness::try_from(&profile).expect("profile converts");

        assert_eq!(harness.command(), "cerberus-peer-harness");
        assert_eq!(harness.configured_args(), ["--harness", "fixture-peer"]);
        assert_eq!(harness.configured_timeout(), Duration::from_secs(2));
    }

    #[test]
    fn command_harness_nonzero_exit_degrades_reviewer() {
        let request = request();
        let config = config();
        let harness = fixture_harness("fail");

        let artifact = review_with_harness(&request, &config, &harness)
            .expect("command failure is represented as degradation");

        assert_eq!(artifact.verdict, Verdict::Skip);
        assert!(artifact.degraded);
        assert_eq!(artifact.reviewer_artifacts[0].status, ReviewerStatus::Error);
        assert!(artifact.reviewer_artifacts[0]
            .degraded_reason
            .as_deref()
            .is_some_and(|reason| reason.contains("fixture command failed")));
        artifact.validate().expect("run artifact validates");
    }

    #[test]
    fn command_harness_timeout_degrades_reviewer() {
        let request = request();
        let config = config();
        let harness = fixture_harness("sleep").timeout(Duration::from_millis(20));

        let artifact = review_with_harness(&request, &config, &harness)
            .expect("command timeout is represented as degradation");

        assert_eq!(artifact.verdict, Verdict::Skip);
        assert!(artifact.degraded);
        assert_eq!(
            artifact.reviewer_artifacts[0].status,
            ReviewerStatus::Timeout
        );
        assert!(artifact.reviewer_artifacts[0]
            .degraded_reason
            .as_deref()
            .is_some_and(|reason| reason.contains("exceeded")));
        artifact.validate().expect("run artifact validates");
    }

    #[test]
    fn command_harness_timeout_terminates_descendant_processes() {
        let request = request();
        let config = config();
        let marker = std::env::temp_dir().join(format!(
            "cerberus-command-harness-child-{}-{}",
            std::process::id(),
            unique_suffix()
        ));
        let fixture = fixture_path();
        let harness = CommandHarness::new("sh")
            .arg(fixture.display().to_string())
            .arg("spawn-child")
            .arg(marker.display().to_string())
            .timeout(Duration::from_millis(20));

        let artifact = review_with_harness(&request, &config, &harness)
            .expect("command timeout is represented as degradation");

        assert_eq!(artifact.verdict, Verdict::Skip);
        assert!(artifact.degraded);
        thread::sleep(Duration::from_millis(500));
        assert!(
            !marker.exists(),
            "descendant process survived command harness timeout"
        );
        let _ = fs::remove_file(marker);
    }

    #[test]
    fn command_harness_timeout_kills_term_ignoring_descendant_processes() {
        let request = request();
        let config = config();
        let marker = std::env::temp_dir().join(format!(
            "cerberus-command-harness-term-child-{}-{}",
            std::process::id(),
            unique_suffix()
        ));
        let fixture = fixture_path();
        let harness = CommandHarness::new("sh")
            .arg(fixture.display().to_string())
            .arg("spawn-ignore-term")
            .arg(marker.display().to_string())
            .timeout(Duration::from_millis(20));

        let artifact = review_with_harness(&request, &config, &harness)
            .expect("command timeout is represented as degradation");

        assert_eq!(artifact.verdict, Verdict::Skip);
        assert!(artifact.degraded);
        thread::sleep(Duration::from_millis(500));
        assert!(
            !marker.exists(),
            "TERM-ignoring descendant process survived command harness timeout"
        );
        let _ = fs::remove_file(marker);
    }

    #[test]
    fn command_harness_failure_diagnostic_is_bounded() {
        let request = request();
        let config = config();
        let harness = fixture_harness("noisy-fail");

        let artifact = review_with_harness(&request, &config, &harness)
            .expect("command failure is represented as degradation");
        let reason = artifact.reviewer_artifacts[0]
            .degraded_reason
            .as_deref()
            .expect("degraded reason is recorded");

        assert!(reason.contains("[truncated]"));
        assert!(reason.len() <= DIAGNOSTIC_MAX_BYTES as usize + 256);
        artifact.validate().expect("run artifact validates");
    }

    #[test]
    fn command_harness_temp_dir_is_private_and_removed() {
        let files =
            CommandHarnessFiles::create("reviewer with spaces").expect("temp files are created");
        let root = files.root.clone();

        #[cfg(unix)]
        {
            let mode = fs::metadata(&root)
                .expect("temp root metadata exists")
                .permissions()
                .mode()
                & 0o777;
            assert_eq!(mode, 0o700);
        }

        drop(files);

        assert!(!root.exists(), "command harness temp root was not removed");
    }

    fn fixture_harness(mode: &str) -> CommandHarness {
        let fixture = fixture_path();
        CommandHarness::new("sh")
            .arg(fixture.display().to_string())
            .arg(mode)
            .timeout(Duration::from_secs(2))
    }

    fn fixture_path() -> PathBuf {
        std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../fixtures/harnesses/command-reviewer.sh")
    }

    fn fixture_peer_profile() -> PeerHarnessCommandProfile {
        cerberus_schema::PeerHarnessCommandProfile {
            harness_id: "fixture-peer".to_string(),
            command: "cerberus-peer-harness".to_string(),
            args: vec!["--harness".to_string(), "fixture-peer".to_string()],
            timeout_ms: 2_000,
            env_required: vec![],
            output_contract: cerberus_schema::PeerHarnessOutputContract::ReviewerArtifactFile,
            peer: cerberus_schema::PeerHarnessInvocation {
                command: "fixture-peer".to_string(),
                args_template: vec!["{prompt}".to_string()],
                prompt_mode: cerberus_schema::PeerHarnessPromptMode::WrapperRenderedPrompt,
                notes: None,
            },
            unsupported: vec!["daemonized children".to_string()],
            notes: None,
        }
    }

    fn config() -> ReviewConfig {
        ReviewConfig {
            schema_version: REVIEW_CONFIG_VERSION.to_string(),
            config_id: "command-harness-test".to_string(),
            reviewers: vec![ReviewerConfig {
                id: "command-reviewer".to_string(),
                perspective: "command".to_string(),
                model: "fixture:model".to_string(),
                fake_behavior: Default::default(),
            }],
            confidence_min: 0.7,
        }
    }

    fn request() -> ReviewRequest {
        ReviewRequest {
            schema_version: REVIEW_REQUEST_VERSION.to_string(),
            request_id: "command-harness-request".to_string(),
            source: ReviewSource::Fixture {
                name: "command-harness".to_string(),
            },
            change: Change {
                title: "Command harness fixture".to_string(),
                description: None,
                base_ref: None,
                head_ref: None,
                head_sha: Some("command-harness-sha".to_string()),
                diff: "diff --git a/src/lib.rs b/src/lib.rs\n+CERBERUS_COMMAND_FINDING\n"
                    .to_string(),
                files: vec![ChangedFile {
                    path: "src/lib.rs".to_string(),
                    status: FileStatus::Modified,
                    additions: 1,
                    deletions: 0,
                }],
            },
            context: ReviewContext {
                summary: None,
                acceptance: vec![],
                linked_artifacts: vec![],
                metadata: BTreeMap::new(),
            },
            caller: Default::default(),
            policy: Default::default(),
        }
    }
}
