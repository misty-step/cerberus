use cerberus_core::{HarnessRuntimeError, ReviewHarness};
use cerberus_schema::{PeerHarnessCommandProfile, ReviewRequest, ReviewerArtifact, ReviewerConfig};
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicU64, Ordering},
        mpsc::{self, TryRecvError},
    },
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

#[cfg(unix)]
use std::os::unix::{fs::PermissionsExt, process::CommandExt};

static NEXT_TEMP_ID: AtomicU64 = AtomicU64::new(0);
const CAPTURE_MAX_BYTES: u64 = 1_048_576;
const DIAGNOSTIC_MAX_BYTES: u64 = 4096;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CommandHarnessInput {
    pub reviewer: ReviewerConfig,
    pub request: ReviewRequest,
}

#[derive(Debug, Clone)]
pub struct BoundedCommand {
    command: String,
    args: Vec<String>,
    timeout: Duration,
    stdin_text: Option<String>,
    capture_max_bytes: u64,
}

impl BoundedCommand {
    pub fn new(command: impl Into<String>) -> Self {
        Self {
            command: command.into(),
            args: vec![],
            timeout: Duration::from_secs(120),
            stdin_text: None,
            capture_max_bytes: CAPTURE_MAX_BYTES,
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

    pub fn stdin_text(mut self, stdin_text: impl Into<String>) -> Self {
        self.stdin_text = Some(stdin_text.into());
        self
    }

    pub fn capture_max_bytes(mut self, capture_max_bytes: u64) -> Self {
        self.capture_max_bytes = capture_max_bytes;
        self
    }

    pub fn run(&self) -> Result<BoundedCommandOutput, HarnessRuntimeError> {
        let files = BoundedCommandFiles::create()?;
        let stdout = create_private_file(&files.stdout).map_err(|error| {
            HarnessRuntimeError::Failed(format!(
                "failed to create bounded command stdout {}: {error}",
                files.stdout.display()
            ))
        })?;
        let stderr = create_private_file(&files.stderr).map_err(|error| {
            HarnessRuntimeError::Failed(format!(
                "failed to create bounded command stderr {}: {error}",
                files.stderr.display()
            ))
        })?;
        let mut command = Command::new(&self.command);
        command
            .args(&self.args)
            .stdout(Stdio::from(stdout))
            .stderr(Stdio::from(stderr));
        if self.stdin_text.is_some() {
            command.stdin(Stdio::piped());
        }
        start_new_process_group(&mut command);
        let mut child = command.spawn().map_err(|error| {
            HarnessRuntimeError::Failed(format!("failed to launch {:?}: {error}", self.command))
        })?;

        let mut stdin_write =
            start_stdin_write(&mut child, self.stdin_text.clone(), &self.command)?;

        let deadline = Instant::now() + self.timeout;
        let status = loop {
            if let Err(error) = poll_stdin_write(&mut stdin_write, &self.command) {
                terminate_process_group(&mut child);
                return Err(error);
            }
            if let Err(error) = ensure_bounded_capture(
                &files.stdout,
                self.capture_max_bytes,
                "stdout",
                &self.command,
            ) {
                terminate_process_group(&mut child);
                return Err(error);
            }
            if let Err(error) = ensure_bounded_capture(
                &files.stderr,
                self.capture_max_bytes,
                "stderr",
                &self.command,
            ) {
                terminate_process_group(&mut child);
                return Err(error);
            }
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
        if let Err(error) = finish_stdin_write(&mut stdin_write, &self.command) {
            terminate_process_group(&mut child);
            return Err(error);
        }

        ensure_bounded_capture(
            &files.stderr,
            self.capture_max_bytes,
            "stderr",
            &self.command,
        )?;
        let stderr = read_bounded_lossy(&files.stderr, DIAGNOSTIC_MAX_BYTES);
        if !status.success() {
            return Err(HarnessRuntimeError::Failed(format!(
                "{:?} exited with {status}: {}",
                self.command,
                stderr.trim()
            )));
        }
        ensure_bounded_capture(
            &files.stdout,
            self.capture_max_bytes,
            "stdout",
            &self.command,
        )?;

        Ok(BoundedCommandOutput {
            stdout: read_bounded_utf8(
                &files.stdout,
                self.capture_max_bytes,
                "stdout",
                &self.command,
            )?,
            stderr,
        })
    }
}

type StdinWriteResult = Result<(), String>;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BoundedCommandOutput {
    pub stdout: String,
    pub stderr: String,
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
        BoundedCommand::new(&self.command)
            .args(self.args.clone())
            .arg("--input")
            .arg(files.input.display().to_string())
            .arg("--output")
            .arg(files.output.display().to_string())
            .timeout(self.timeout)
            .run()?;

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
        })
    }
}

#[derive(Debug)]
struct BoundedCommandFiles {
    root: PathBuf,
    stdout: PathBuf,
    stderr: PathBuf,
}

impl Drop for BoundedCommandFiles {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

impl BoundedCommandFiles {
    fn create() -> Result<Self, HarnessRuntimeError> {
        let root = std::env::temp_dir().join(format!(
            "cerberus-bounded-command-{}-{}",
            std::process::id(),
            unique_suffix()
        ));
        fs::create_dir(&root).map_err(|error| {
            HarnessRuntimeError::Failed(format!(
                "failed to create bounded command temp dir {}: {error}",
                root.display()
            ))
        })?;
        if let Err(error) = set_private_dir_permissions(&root) {
            let _ = fs::remove_dir_all(&root);
            return Err(HarnessRuntimeError::Failed(format!(
                "failed to restrict bounded command temp dir {}: {error}",
                root.display()
            )));
        }
        Ok(Self {
            root: root.clone(),
            stdout: root.join("stdout.txt"),
            stderr: root.join("stderr.txt"),
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

fn start_stdin_write(
    child: &mut Child,
    stdin_text: Option<String>,
    command: &str,
) -> Result<Option<mpsc::Receiver<StdinWriteResult>>, HarnessRuntimeError> {
    let Some(stdin_text) = stdin_text else {
        return Ok(None);
    };
    let mut stdin = child.stdin.take().ok_or_else(|| {
        HarnessRuntimeError::Failed(format!("failed to open stdin for {command:?}"))
    })?;
    let command = command.to_string();
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || {
        let result = stdin
            .write_all(stdin_text.as_bytes())
            .map_err(|error| format!("failed to write stdin for {command:?}: {error}"));
        let _ = sender.send(result);
    });
    Ok(Some(receiver))
}

fn poll_stdin_write(
    stdin_write: &mut Option<mpsc::Receiver<StdinWriteResult>>,
    command: &str,
) -> Result<(), HarnessRuntimeError> {
    let Some(receiver) = stdin_write.as_ref() else {
        return Ok(());
    };
    match receiver.try_recv() {
        Ok(Ok(())) => {
            *stdin_write = None;
            Ok(())
        }
        Ok(Err(error)) => Err(HarnessRuntimeError::Failed(error)),
        Err(TryRecvError::Empty) => Ok(()),
        Err(TryRecvError::Disconnected) => Err(HarnessRuntimeError::Failed(format!(
            "stdin writer for {command:?} disconnected"
        ))),
    }
}

fn finish_stdin_write(
    stdin_write: &mut Option<mpsc::Receiver<StdinWriteResult>>,
    command: &str,
) -> Result<(), HarnessRuntimeError> {
    let Some(receiver) = stdin_write.take() else {
        return Ok(());
    };
    match receiver.recv_timeout(Duration::from_millis(100)) {
        Ok(Ok(())) => Ok(()),
        Ok(Err(error)) => Err(HarnessRuntimeError::Failed(error)),
        Err(error) => Err(HarnessRuntimeError::Failed(format!(
            "stdin writer for {command:?} did not finish after child exit: {error}"
        ))),
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

fn read_bounded_utf8(
    path: &Path,
    max_bytes: u64,
    stream: &'static str,
    command: &str,
) -> Result<String, HarnessRuntimeError> {
    let mut file = File::open(path).map_err(|error| {
        HarnessRuntimeError::Failed(format!("failed to read {stream} for {command:?}: {error}"))
    })?;
    let mut bytes = Vec::new();
    Read::by_ref(&mut file)
        .take(max_bytes)
        .read_to_end(&mut bytes)
        .map_err(|error| {
            HarnessRuntimeError::Failed(format!("failed to read {stream} for {command:?}: {error}"))
        })?;
    String::from_utf8(bytes).map_err(|error| {
        HarnessRuntimeError::Failed(format!("{command:?} {stream} was not valid UTF-8: {error}"))
    })
}

fn ensure_bounded_capture(
    path: &Path,
    max_bytes: u64,
    stream: &'static str,
    command: &str,
) -> Result<(), HarnessRuntimeError> {
    let length = fs::metadata(path)
        .map(|metadata| metadata.len())
        .unwrap_or(0);
    if length > max_bytes {
        return Err(HarnessRuntimeError::Failed(format!(
            "{command:?} {stream} exceeded {max_bytes} bytes"
        )));
    }
    Ok(())
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
    fn bounded_command_captures_stdout_stderr_and_stdin() {
        let output = BoundedCommand::new("sh")
            .arg("-c")
            .arg("cat; printf fixture-stderr >&2")
            .stdin_text("fixture-stdin")
            .timeout(Duration::from_secs(2))
            .run()
            .expect("bounded command runs");

        assert_eq!(output.stdout, "fixture-stdin");
        assert_eq!(output.stderr, "fixture-stderr");
    }

    #[test]
    fn bounded_command_rejects_oversized_stdout() {
        let error = BoundedCommand::new("sh")
            .arg("-c")
            .arg("printf 1234567890")
            .capture_max_bytes(4)
            .timeout(Duration::from_secs(2))
            .run()
            .expect_err("oversized stdout rejects");

        assert!(error.to_string().contains("stdout exceeded 4 bytes"));
    }

    #[test]
    fn bounded_command_timeout_covers_blocked_stdin_writer() {
        let large_stdin = "x".repeat(2_000_000);
        let started = Instant::now();
        let error = BoundedCommand::new("sh")
            .arg("-c")
            .arg("sleep 2")
            .stdin_text(large_stdin)
            .timeout(Duration::from_millis(50))
            .run()
            .expect_err("blocked stdin writer must not bypass timeout");

        assert!(error.to_string().contains("exceeded 50 ms"));
        assert!(started.elapsed() < Duration::from_secs(1));
    }

    #[test]
    fn bounded_command_kills_stdin_holding_descendant_after_child_exit() {
        let marker = std::env::temp_dir().join(format!(
            "cerberus-stdin-descendant-marker-{}-{}",
            std::process::id(),
            unique_suffix()
        ));
        let script = format!(
            "(sleep 1; printf leaked > {}) &",
            shell_single_quote(&marker.display().to_string())
        );
        let large_stdin = "x".repeat(2_000_000);

        let error = BoundedCommand::new("sh")
            .arg("-c")
            .arg(script)
            .stdin_text(large_stdin)
            .timeout(Duration::from_secs(2))
            .run()
            .expect_err("blocked descendant stdin writer rejects");

        assert!(!error.to_string().is_empty());
        thread::sleep(Duration::from_millis(1200));
        assert!(!marker.exists());
        let _ = fs::remove_file(marker);
    }

    #[test]
    fn bounded_command_rejects_invalid_utf8_stdout() {
        let error = BoundedCommand::new("sh")
            .arg("-c")
            .arg("printf '\\377'")
            .timeout(Duration::from_secs(2))
            .run()
            .expect_err("invalid utf-8 stdout rejects");

        assert!(error.to_string().contains("stdout was not valid UTF-8"));
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

    fn shell_single_quote(value: &str) -> String {
        format!("'{}'", value.replace('\'', "'\\''"))
    }

    fn fixture_peer_profile() -> PeerHarnessCommandProfile {
        cerberus_schema::PeerHarnessCommandProfile {
            harness_id: "fixture-peer".to_string(),
            command: "cerberus-peer-harness".to_string(),
            args: vec!["--harness".to_string(), "fixture-peer".to_string()],
            timeout_ms: 2_000,
            env_required: vec![],
            requires_provider_budget_ack: false,
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
