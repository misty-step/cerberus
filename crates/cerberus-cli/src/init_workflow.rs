use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
};

const DEFAULT_TEMPLATE_SOURCE: &str = "embedded:templates/consumer-workflow-reusable.yml";
const DEFAULT_WORKFLOW_TEMPLATE: &str =
    include_str!("../../../templates/consumer-workflow-reusable.yml");
const WORKFLOW_RELATIVE_PATH: &str = ".github/workflows/cerberus.yml";
const SECRET_CONFIGURATION_STATUS: &str = "not_configured_by_init_workflow";

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

#[derive(Debug)]
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
}
