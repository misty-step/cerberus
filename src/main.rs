use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;

use anyhow::{Context, Result};
use cerberus::harness::{ExecutionPlan, HarnessKind, ReviewHarness};
use cerberus::{
    render_markdown, validate_artifact_for_request, validate_request, ReviewArtifact, ReviewRequest,
};
use clap::{Args, Parser, Subcommand};

#[derive(Debug, Parser)]
#[command(name = "cerberus")]
#[command(about = "Context-adaptive code review runner")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    Review(Box<ReviewArgs>),
    Render(RenderArgs),
}

#[derive(Debug, Args)]
struct ReviewArgs {
    #[arg(long)]
    request: PathBuf,
    #[arg(long)]
    out: PathBuf,
    #[arg(long)]
    markdown: Option<PathBuf>,
    #[arg(long, value_enum, default_value_t = HarnessKind::Opencode)]
    harness: HarnessKind,
    #[arg(long)]
    fixture_output: Option<PathBuf>,
    #[arg(long, default_value = "opencode")]
    opencode_binary: String,
    #[arg(long)]
    opencode_attach: Option<String>,
    #[arg(long, default_value = "omp")]
    omp_binary: String,
    #[arg(long)]
    model: Option<String>,
    #[arg(long)]
    cwd: Option<PathBuf>,
    #[arg(long)]
    timeout_seconds: Option<u64>,
    #[arg(long)]
    execution_plan: Option<PathBuf>,
    #[arg(long)]
    transcript: Option<PathBuf>,
}

#[derive(Debug, Args)]
struct RenderArgs {
    #[arg(long)]
    artifact: PathBuf,
    #[arg(long)]
    markdown: PathBuf,
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Command::Review(args) => review(*args),
        Command::Render(args) => render(args),
    }
}

fn review(args: ReviewArgs) -> Result<()> {
    let ReviewArgs {
        request,
        out,
        markdown,
        harness,
        fixture_output,
        opencode_binary,
        opencode_attach,
        omp_binary,
        model,
        cwd,
        timeout_seconds,
        execution_plan,
        transcript,
    } = args;
    let request = read_json::<ReviewRequest>(&request)?;
    validate_request(&request)?;
    let cwd = cwd.unwrap_or(std::env::current_dir().context("read current directory")?);
    let timeout = timeout_seconds
        .map(Duration::from_secs)
        .unwrap_or_else(|| Duration::from_millis(request.policy.timeout_ms));
    let review_harness = ReviewHarness {
        kind: harness,
        fixture_output,
        opencode_binary,
        opencode_attach,
        omp_binary,
        model,
        timeout,
    };
    let run = review_harness.run(&request, &cwd)?;
    validate_artifact_for_request(&run.artifact, &request)?;

    write_json(&out, &run.artifact)?;
    if let Some(markdown) = markdown {
        write_text(&markdown, &render_markdown(&run.artifact))?;
    }
    let plan_path = execution_plan.unwrap_or_else(|| sibling_path(&out, "execution_plan.json"));
    write_json(&plan_path, &run.execution_plan)?;
    if let Some(transcript_path) = transcript {
        write_text(&transcript_path, &run.transcript)?;
    }
    Ok(())
}

fn render(args: RenderArgs) -> Result<()> {
    let artifact = read_json::<ReviewArtifact>(&args.artifact)?;
    write_text(&args.markdown, &render_markdown(&artifact))?;
    Ok(())
}

fn read_json<T>(path: &Path) -> Result<T>
where
    T: serde::de::DeserializeOwned,
{
    let text = fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
    serde_json::from_str(&text).with_context(|| format!("parse JSON {}", path.display()))
}

fn write_json<T>(path: &Path, value: &T) -> Result<()>
where
    T: serde::Serialize,
{
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).with_context(|| format!("create {}", parent.display()))?;
    }
    let text = serde_json::to_string_pretty(value).context("serialize JSON")?;
    write_text(path, &(text + "\n"))
}

fn write_text(path: &Path, text: &str) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).with_context(|| format!("create {}", parent.display()))?;
    }
    fs::write(path, text).with_context(|| format!("write {}", path.display()))
}

fn sibling_path(out: &Path, filename: &str) -> PathBuf {
    out.parent()
        .map(|parent| parent.join(filename))
        .unwrap_or_else(|| PathBuf::from(filename))
}

#[allow(dead_code)]
fn _assert_plan_is_serializable(plan: &ExecutionPlan) -> Result<String> {
    serde_json::to_string(plan).context("serialize execution plan")
}
