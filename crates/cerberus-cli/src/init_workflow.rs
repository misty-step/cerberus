use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use std::{
    env, fs,
    io::{self, IsTerminal, Read, Write},
    path::{Path, PathBuf},
    process::{Command, Stdio},
};

#[cfg(unix)]
use std::os::fd::AsRawFd;

const DEFAULT_TEMPLATE_SOURCE: &str = "embedded:templates/consumer-workflow-reusable.yml";
const DEFAULT_WORKFLOW_TEMPLATE: &str =
    include_str!("../../../templates/consumer-workflow-reusable.yml");
const WORKFLOW_RELATIVE_PATH: &str = ".github/workflows/cerberus.yml";
const SECRET_CONFIGURATION_STATUS: &str = "not_configured_by_init_workflow";
const SECRET_CONFIGURED_STATUS: &str = "configured_by_gh_secret_set";
const SECRET_NAME: &str = "CERBERUS_API_KEY";
const DEFAULT_GH_COMMAND: &str = "gh";

pub(crate) fn init(args: Vec<String>) -> Result<()> {
    let args = InitArgs::parse(&args)?;
    let secret = read_secret_for_init(&args)?;
    let report = run_init_with_secret(&args, secret.as_deref())?;
    if let Some(report_out) = &args.workflow.report_out {
        write_report(report_out, &report)?;
    }

    println!("{}", report.summary_line());
    println!("Secret configuration: {}", report.secret_configuration);
    if report.changed {
        println!(
            "Run: git add {WORKFLOW_RELATIVE_PATH} && git commit -m \"Add Cerberus workflow\""
        );
    } else {
        println!("No workflow file changes to commit.");
    }
    Ok(())
}

pub(crate) fn init_workflow(args: Vec<String>) -> Result<()> {
    let args = InitWorkflowArgs::parse(&args)?;
    let report = run_init_workflow(&args)?;
    if let Some(report_out) = &args.report_out {
        write_report(report_out, &report)?;
    }

    println!("{}", report.summary_line());
    println!("Secret configuration: {SECRET_CONFIGURATION_STATUS}");
    Ok(())
}

#[derive(Debug, Clone)]
pub(crate) struct InitArgs {
    workflow: InitWorkflowArgs,
    api_key_stdin: bool,
    gh_command: PathBuf,
}

impl InitArgs {
    fn parse(args: &[String]) -> Result<Self> {
        let mut workflow_args = Vec::new();
        let mut api_key_stdin = false;
        let gh_command = PathBuf::from(DEFAULT_GH_COMMAND);
        let mut index = 0;

        while index < args.len() {
            match args[index].as_str() {
                "--api-key-stdin" => {
                    api_key_stdin = true;
                    index += 1;
                }
                "--repo-root" | "--template" | "--report-out" => {
                    workflow_args.push(args[index].clone());
                    workflow_args.push(required_arg(args, index, &args[index])?);
                    index += 2;
                }
                other => bail!("unknown init argument {other:?}"),
            }
        }

        Ok(Self {
            workflow: InitWorkflowArgs::parse(&workflow_args)?,
            api_key_stdin,
            gh_command,
        })
    }
}

#[derive(Debug, Clone)]
pub(crate) struct InitWorkflowArgs {
    repo_root: Option<PathBuf>,
    template: Option<PathBuf>,
    report_out: Option<PathBuf>,
}

impl InitWorkflowArgs {
    fn parse(args: &[String]) -> Result<Self> {
        let mut repo_root = None;
        let mut template = None;
        let mut report_out = None;
        let mut index = 0;

        while index < args.len() {
            match args[index].as_str() {
                "--repo-root" => {
                    repo_root = Some(PathBuf::from(required_arg(args, index, "--repo-root")?));
                    index += 2;
                }
                "--template" => {
                    template = Some(PathBuf::from(required_arg(args, index, "--template")?));
                    index += 2;
                }
                "--report-out" => {
                    report_out = Some(PathBuf::from(required_arg(args, index, "--report-out")?));
                    index += 2;
                }
                other => bail!("unknown init-workflow argument {other:?}"),
            }
        }

        Ok(Self {
            repo_root,
            template,
            report_out,
        })
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub(crate) struct InitWorkflowReport {
    pub status: InitWorkflowStatus,
    pub changed: bool,
    pub skipped: bool,
    pub repo_root: String,
    pub workflow_path: String,
    pub template_source: String,
    pub secret_configuration: String,
}

impl InitWorkflowReport {
    fn summary_line(&self) -> String {
        match self.status {
            InitWorkflowStatus::Created => format!("Created {}", self.workflow_path),
            InitWorkflowStatus::UpToDate => format!("Up-to-date: {}", self.workflow_path),
            InitWorkflowStatus::PreservedExisting => format!(
                "Left unchanged: {} (existing file differs from template)",
                self.workflow_path
            ),
        }
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub(crate) enum InitWorkflowStatus {
    Created,
    UpToDate,
    PreservedExisting,
}

pub(crate) fn run_init_workflow(args: &InitWorkflowArgs) -> Result<InitWorkflowReport> {
    let repo_root = match &args.repo_root {
        Some(path) => path.clone(),
        None => detect_repo_root()?,
    };
    if !repo_root.is_dir() {
        bail!(
            "init-workflow repo root does not exist: {}",
            repo_root.display()
        );
    }

    let (template, template_source) = match &args.template {
        Some(path) => (
            fs::read_to_string(path)
                .with_context(|| format!("failed to read workflow template {}", path.display()))?,
            path.display().to_string(),
        ),
        None => (
            DEFAULT_WORKFLOW_TEMPLATE.to_string(),
            DEFAULT_TEMPLATE_SOURCE.to_string(),
        ),
    };

    scaffold_workflow(&repo_root, &template, &template_source)
}

pub(crate) fn run_init_with_secret(
    args: &InitArgs,
    secret_value: Option<&str>,
) -> Result<InitWorkflowReport> {
    let repo_root = match &args.workflow.repo_root {
        Some(path) => path.clone(),
        None => detect_repo_root()?,
    };

    let secret = secret_value
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .context("init requires CERBERUS_API_KEY or --api-key-stdin")?;

    let workflow_args = InitWorkflowArgs {
        repo_root: Some(repo_root.clone()),
        template: args.workflow.template.clone(),
        report_out: args.workflow.report_out.clone(),
    };
    let mut report = run_init_workflow(&workflow_args)?;

    set_github_secret(&repo_root, &args.gh_command, secret)?;
    report.secret_configuration = SECRET_CONFIGURED_STATUS.to_string();

    Ok(report)
}

fn scaffold_workflow(
    repo_root: &Path,
    template: &str,
    template_source: &str,
) -> Result<InitWorkflowReport> {
    let workflow_path = repo_root.join(WORKFLOW_RELATIVE_PATH);
    if let Some(parent) = workflow_path.parent() {
        fs::create_dir_all(parent)
            .with_context(|| format!("failed to create workflow directory {}", parent.display()))?;
    }

    let (status, changed, skipped) = if !workflow_path.exists() {
        fs::write(&workflow_path, template)
            .with_context(|| format!("failed to write {}", workflow_path.display()))?;
        (InitWorkflowStatus::Created, true, false)
    } else {
        let existing = fs::read_to_string(&workflow_path)
            .with_context(|| format!("failed to read {}", workflow_path.display()))?;
        if existing.trim() == template.trim() {
            (InitWorkflowStatus::UpToDate, false, false)
        } else {
            (InitWorkflowStatus::PreservedExisting, false, true)
        }
    };

    Ok(InitWorkflowReport {
        status,
        changed,
        skipped,
        repo_root: repo_root.display().to_string(),
        workflow_path: WORKFLOW_RELATIVE_PATH.to_string(),
        template_source: template_source.to_string(),
        secret_configuration: SECRET_CONFIGURATION_STATUS.to_string(),
    })
}

fn read_secret_for_init(args: &InitArgs) -> Result<Option<String>> {
    if args.api_key_stdin {
        if io::stdin().is_terminal() {
            bail!("refusing to read API key from an interactive terminal with --api-key-stdin");
        }
        let mut secret = String::new();
        io::stdin()
            .read_to_string(&mut secret)
            .context("failed to read API key from stdin")?;
        let secret = secret.trim().to_string();
        if secret.is_empty() {
            bail!("API key from stdin was empty");
        }
        return Ok(Some(secret));
    }

    let secret = env::var(SECRET_NAME).unwrap_or_default().trim().to_string();
    if secret.is_empty() {
        return read_hidden_secret_from_tty();
    }
    Ok(Some(secret))
}

#[cfg(unix)]
fn read_hidden_secret_from_tty() -> Result<Option<String>> {
    let mut stdin = io::stdin();
    if !stdin.is_terminal() {
        bail!("init requires CERBERUS_API_KEY, --api-key-stdin, or an interactive TTY");
    }

    let mut stdout = io::stdout();
    stdout
        .write_all(b"Enter Cerberus API key (input hidden): ")
        .context("failed to write API key prompt")?;
    stdout.flush().context("failed to flush API key prompt")?;

    let mut guard = EchoGuard::disable(stdin.as_raw_fd())?;
    let read_result = read_hidden_line(&mut stdin);
    let restore_result = guard.restore();
    stdout
        .write_all(b"\n")
        .context("failed to finish API key prompt")?;
    stdout.flush().context("failed to flush API key prompt")?;

    let secret = read_result.context("failed to read API key from TTY")?;
    restore_result?;

    let secret = secret.trim().to_string();
    if secret.is_empty() {
        bail!("No API key entered.");
    }
    Ok(Some(secret))
}

#[cfg(unix)]
fn read_hidden_line(input: &mut impl Read) -> io::Result<String> {
    let mut value = Vec::new();
    let mut escape_state = EscapeState::None;

    loop {
        let mut byte = [0_u8; 1];
        if input.read(&mut byte)? == 0 {
            return Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                "No API key entered.",
            ));
        }

        match (escape_state, byte[0]) {
            (_, b'\r' | b'\n') => break,
            (_, 3 | 4) => {
                return Err(io::Error::new(
                    io::ErrorKind::Interrupted,
                    "No API key entered.",
                ));
            }
            (_, 8 | 127) => {
                value.pop();
                escape_state = EscapeState::None;
            }
            (_, 0x1b) => {
                escape_state = EscapeState::Esc;
            }
            (EscapeState::Esc, b'[' | b'O') => {
                escape_state = EscapeState::Sequence;
            }
            (EscapeState::Esc, byte) => {
                escape_state = if is_escape_sequence_terminator(byte) {
                    EscapeState::None
                } else {
                    EscapeState::Sequence
                };
            }
            (EscapeState::Sequence, byte) => {
                if is_escape_sequence_terminator(byte) {
                    escape_state = EscapeState::None;
                }
            }
            (EscapeState::None, byte) if byte < b' ' => {}
            (EscapeState::None, byte) => value.push(byte),
        }
    }

    String::from_utf8(value)
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "API key was not UTF-8"))
}

#[cfg(unix)]
#[derive(Clone, Copy)]
enum EscapeState {
    None,
    Esc,
    Sequence,
}

#[cfg(unix)]
fn is_escape_sequence_terminator(byte: u8) -> bool {
    (b'@'..=b'~').contains(&byte)
}

#[cfg(not(unix))]
fn read_hidden_secret_from_tty() -> Result<Option<String>> {
    bail!(
        "init requires CERBERUS_API_KEY or --api-key-stdin; interactive hidden prompt is unavailable on this platform"
    );
}

#[cfg(unix)]
struct EchoGuard {
    fd: i32,
    original: libc::termios,
    active: bool,
}

#[cfg(unix)]
impl EchoGuard {
    fn disable(fd: i32) -> Result<Self> {
        let mut original = std::mem::MaybeUninit::<libc::termios>::uninit();
        if unsafe { libc::tcgetattr(fd, original.as_mut_ptr()) } != 0 {
            return Err(io::Error::last_os_error()).context("failed to read terminal settings");
        }
        let original = unsafe { original.assume_init() };
        let mut hidden = original;
        hidden.c_lflag &= !(libc::ECHO | libc::ICANON | libc::ISIG);
        hidden.c_cc[libc::VMIN] = 1;
        hidden.c_cc[libc::VTIME] = 0;
        if unsafe { libc::tcsetattr(fd, libc::TCSANOW, &hidden) } != 0 {
            return Err(io::Error::last_os_error()).context("failed to hide terminal input");
        }

        Ok(Self {
            fd,
            original,
            active: true,
        })
    }

    fn restore(&mut self) -> Result<()> {
        if self.active {
            if unsafe { libc::tcsetattr(self.fd, libc::TCSANOW, &self.original) } != 0 {
                return Err(io::Error::last_os_error()).context("failed to restore terminal input");
            }
            self.active = false;
        }
        Ok(())
    }
}

#[cfg(unix)]
impl Drop for EchoGuard {
    fn drop(&mut self) {
        let _ = self.restore();
    }
}

fn set_github_secret(repo_root: &Path, gh_command: &Path, secret: &str) -> Result<()> {
    let gh_command = resolved_command_path(gh_command)?;
    let mut child = Command::new(&gh_command)
        .args(["secret", "set", SECRET_NAME])
        .current_dir(repo_root)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .env_remove(SECRET_NAME)
        .spawn()
        .with_context(|| format!("failed to launch {}", gh_command.display()))?;

    {
        let mut stdin = child
            .stdin
            .take()
            .context("failed to open gh stdin for secret setup")?;
        stdin
            .write_all(secret.as_bytes())
            .context("failed to write API key to gh stdin")?;
    }

    let output = child
        .wait_with_output()
        .context("failed to wait for gh secret set")?;
    if output.status.success() {
        return Ok(());
    }

    let stderr = String::from_utf8_lossy(&output.stderr);
    let stdout = String::from_utf8_lossy(&output.stdout);
    let message = if stderr.trim().is_empty() {
        stdout.trim()
    } else {
        stderr.trim()
    };
    bail!(
        "Failed to set {SECRET_NAME} in repository secrets: {}",
        redact_secret(message, secret)
    );
}

fn resolved_command_path(command: &Path) -> Result<PathBuf> {
    if command.components().count() > 1 {
        command
            .canonicalize()
            .with_context(|| format!("failed to resolve {}", command.display()))
    } else {
        Ok(command.to_path_buf())
    }
}

fn redact_secret(message: &str, secret: &str) -> String {
    if secret.is_empty() {
        message.to_string()
    } else {
        message.replace(secret, "[redacted]")
    }
}

fn detect_repo_root() -> Result<PathBuf> {
    let output = Command::new("git")
        .args(["rev-parse", "--show-toplevel"])
        .output()
        .context("failed to launch git; pass --repo-root <path>")?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        bail!(
            "init-workflow requires --repo-root <path> or a git repository: {}",
            stderr.trim()
        );
    }
    let stdout = String::from_utf8(output.stdout).context("git output was not UTF-8")?;
    let root = stdout.trim();
    if root.is_empty() {
        bail!("git rev-parse --show-toplevel returned an empty path");
    }
    Ok(PathBuf::from(root))
}

fn required_arg(args: &[String], index: usize, flag: &str) -> Result<String> {
    let Some(value) = args.get(index + 1) else {
        bail!("{flag} requires a value");
    };
    if value.starts_with("--") {
        bail!("{flag} requires a value");
    }
    Ok(value.clone())
}

fn write_report(path: &Path, report: &InitWorkflowReport) -> Result<()> {
    let json = serde_json::to_string_pretty(report)?;
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        fs::create_dir_all(parent)
            .with_context(|| format!("failed to create report dir {}", parent.display()))?;
    }
    fs::write(path, format!("{json}\n"))
        .with_context(|| format!("failed to write {}", path.display()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        env,
        time::{SystemTime, UNIX_EPOCH},
    };

    #[test]
    fn init_configures_secret_with_fake_gh_and_redacted_report() {
        let root = temp_repo("init-secret");
        let fake_gh = fake_gh(&root, 0, None);
        let _env_guard = EnvGuard::set(SECRET_NAME, "parent-secret-value");
        let args = InitArgs {
            workflow: InitWorkflowArgs {
                repo_root: Some(root.clone()),
                template: None,
                report_out: Some(root.join("report.json")),
            },
            api_key_stdin: false,
            gh_command: fake_gh,
        };

        let report = run_init_with_secret(&args, Some("test-secret-value")).expect("init succeeds");
        write_report(
            args.workflow.report_out.as_ref().expect("report path"),
            &report,
        )
        .expect("report");

        assert_eq!(report.secret_configuration, SECRET_CONFIGURED_STATUS);
        assert_eq!(
            fs::read_to_string(root.join("gh-args.txt")).expect("gh args"),
            "secret\nset\nCERBERUS_API_KEY\n"
        );
        assert_eq!(
            fs::read_to_string(root.join("gh-stdin.txt")).expect("gh stdin"),
            "test-secret-value"
        );
        assert_eq!(
            fs::read_to_string(root.join("gh-env.txt")).expect("gh env"),
            "unset\n"
        );
        let report_json =
            fs::read_to_string(args.workflow.report_out.as_ref().expect("report path"))
                .expect("report json");
        assert!(!report_json.contains("test-secret-value"));
        cleanup(&root);
    }

    #[test]
    fn init_fails_closed_without_secret_before_writing_workflow() {
        let root = temp_repo("missing-secret");
        let args = InitArgs {
            workflow: InitWorkflowArgs {
                repo_root: Some(root.clone()),
                template: None,
                report_out: None,
            },
            api_key_stdin: false,
            gh_command: root.join("missing-gh"),
        };

        let error = run_init_with_secret(&args, None).expect_err("missing secret rejected");

        assert!(error.to_string().contains("requires CERBERUS_API_KEY"));
        assert!(!root.join(WORKFLOW_RELATIVE_PATH).exists());
        cleanup(&root);
    }

    #[test]
    fn init_redacts_secret_from_gh_failure() {
        let root = temp_repo("gh-failure");
        let fake_gh = fake_gh(&root, 7, Some("gh saw test-secret-value"));
        let args = InitArgs {
            workflow: InitWorkflowArgs {
                repo_root: Some(root.clone()),
                template: None,
                report_out: None,
            },
            api_key_stdin: false,
            gh_command: fake_gh,
        };

        let error = run_init_with_secret(&args, Some("test-secret-value")).expect_err("gh failure");
        let message = error.to_string();

        assert!(message.contains("[redacted]"));
        assert!(!message.contains("test-secret-value"));
        cleanup(&root);
    }

    #[test]
    fn init_workflow_creates_missing_workflow_from_template() {
        let root = temp_repo("creates");

        let report = scaffold_workflow(&root, "name: Cerberus\n", "test-template")
            .expect("workflow created");

        assert_eq!(report.status, InitWorkflowStatus::Created);
        assert!(report.changed);
        assert!(!report.skipped);
        assert_eq!(
            fs::read_to_string(root.join(WORKFLOW_RELATIVE_PATH)).expect("workflow"),
            "name: Cerberus\n"
        );
        cleanup(&root);
    }

    #[test]
    fn init_workflow_reports_up_to_date_without_rewriting_trim_equal_file() {
        let root = temp_repo("up-to-date");
        let workflow = root.join(WORKFLOW_RELATIVE_PATH);
        fs::create_dir_all(workflow.parent().expect("workflow parent")).expect("parent");
        fs::write(&workflow, "name: Cerberus\n\n").expect("existing workflow");

        let report = scaffold_workflow(&root, "name: Cerberus\n", "test-template")
            .expect("workflow checked");

        assert_eq!(report.status, InitWorkflowStatus::UpToDate);
        assert!(!report.changed);
        assert!(!report.skipped);
        assert_eq!(
            fs::read_to_string(workflow).expect("workflow remains"),
            "name: Cerberus\n\n"
        );
        cleanup(&root);
    }

    #[test]
    fn init_workflow_preserves_different_existing_workflow() {
        let root = temp_repo("preserves");
        let workflow = root.join(WORKFLOW_RELATIVE_PATH);
        fs::create_dir_all(workflow.parent().expect("workflow parent")).expect("parent");
        fs::write(&workflow, "name: Custom\n").expect("existing workflow");

        let report = scaffold_workflow(&root, "name: Cerberus\n", "test-template")
            .expect("workflow checked");

        assert_eq!(report.status, InitWorkflowStatus::PreservedExisting);
        assert!(!report.changed);
        assert!(report.skipped);
        assert_eq!(
            fs::read_to_string(workflow).expect("workflow remains"),
            "name: Custom\n"
        );
        cleanup(&root);
    }

    #[test]
    fn init_workflow_writes_report_json() {
        let root = temp_repo("report");
        let template = root.join("template.yml");
        let report_out = root.join("report.json");
        fs::write(&template, "name: Cerberus\n").expect("template");
        let args = InitWorkflowArgs {
            repo_root: Some(root.clone()),
            template: Some(template.clone()),
            report_out: Some(report_out.clone()),
        };

        let report = run_init_workflow(&args).expect("workflow run");
        write_report(&report_out, &report).expect("report");
        let raw = fs::read_to_string(report_out).expect("report json");

        assert!(raw.contains("\"status\": \"created\""));
        assert!(raw.contains("\"secret_configuration\": \"not_configured_by_init_workflow\""));
        cleanup(&root);
    }

    #[test]
    fn hidden_line_handles_backspace_and_escape_sequences() {
        let mut input = b"abc\x7fd\x1b[Ae\n".as_slice();

        let secret = read_hidden_line(&mut input).expect("hidden line");

        assert_eq!(secret, "abde");
    }

    #[test]
    fn hidden_line_treats_ctrl_c_as_empty_secret() {
        let mut input = b"abc\x03".as_slice();

        let error = read_hidden_line(&mut input).expect_err("ctrl-c exits prompt");

        assert_eq!(error.kind(), io::ErrorKind::Interrupted);
    }

    fn temp_repo(name: &str) -> PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        let root = env::temp_dir().join(format!(
            "cerberus-init-workflow-{name}-{}-{nanos}",
            std::process::id()
        ));
        if root.exists() {
            fs::remove_dir_all(&root).expect("remove old temp repo");
        }
        fs::create_dir_all(&root).expect("temp repo");
        root
    }

    fn cleanup(root: &Path) {
        let _ = fs::remove_dir_all(root);
    }

    struct EnvGuard {
        key: &'static str,
        previous: Option<std::ffi::OsString>,
    }

    impl EnvGuard {
        fn set(key: &'static str, value: &str) -> Self {
            let previous = env::var_os(key);
            env::set_var(key, value);
            Self { key, previous }
        }
    }

    impl Drop for EnvGuard {
        fn drop(&mut self) {
            if let Some(previous) = &self.previous {
                env::set_var(self.key, previous);
            } else {
                env::remove_var(self.key);
            }
        }
    }

    #[cfg(unix)]
    fn fake_gh(root: &Path, exit_code: i32, stderr: Option<&str>) -> PathBuf {
        use std::os::unix::fs::PermissionsExt;

        let path = root.join("fake-gh.sh");
        let stderr_line = stderr
            .map(|message| format!("printf '%s\\n' {:?} >&2\n", message))
            .unwrap_or_default();
        let script = format!(
            "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$PWD/gh-args.txt\"\nprintf '%s\\n' \"${{CERBERUS_API_KEY-unset}}\" > \"$PWD/gh-env.txt\"\ncat > \"$PWD/gh-stdin.txt\"\n{}exit {}\n",
            stderr_line, exit_code
        );
        fs::write(&path, script).expect("fake gh script");
        let mut permissions = fs::metadata(&path).expect("fake gh metadata").permissions();
        permissions.set_mode(0o700);
        fs::set_permissions(&path, permissions).expect("fake gh permissions");
        path
    }
}
