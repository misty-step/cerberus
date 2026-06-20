use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;

use anyhow::{Context, Result};
use cerberus::harness::{ExecutionPlan, HarnessKind, ReviewHarness};
use cerberus::request::{
    build_git_range_request, build_pull_request, GitRangeRequestOptions, PullRequestOptions,
    RequestOptions,
};
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
    Request(RequestArgs),
    Review(Box<ReviewArgs>),
    Render(RenderArgs),
}

#[derive(Debug, Args)]
struct RequestArgs {
    #[command(subcommand)]
    command: RequestCommand,
}

#[derive(Debug, Subcommand)]
enum RequestCommand {
    GitRange(GitRangeArgs),
    Pr(PullRequestArgs),
}

#[derive(Debug, Args)]
struct GitRangeArgs {
    #[arg(long, default_value = ".")]
    repo_path: PathBuf,
    #[arg(long)]
    base: String,
    #[arg(long, default_value = "HEAD")]
    head: String,
    #[arg(long)]
    out: PathBuf,
    #[arg(long)]
    title: Option<String>,
    #[arg(long)]
    description: Option<String>,
    #[arg(long)]
    request_id: Option<String>,
    #[arg(long)]
    repo: Option<String>,
    #[arg(long = "instruction")]
    instructions: Vec<String>,
    #[arg(long = "allow-env")]
    allowed_env: Vec<String>,
    #[arg(long, default_value_t = 120)]
    timeout_seconds: u64,
}

#[derive(Debug, Args)]
struct PullRequestArgs {
    #[arg(long)]
    number: u64,
    #[arg(long)]
    out: PathBuf,
    #[arg(long)]
    repo: Option<String>,
    #[arg(long)]
    head_workspace: Option<PathBuf>,
    #[arg(long)]
    request_id: Option<String>,
    #[arg(long = "instruction")]
    instructions: Vec<String>,
    #[arg(long = "allow-env")]
    allowed_env: Vec<String>,
    #[arg(long, default_value_t = 120)]
    timeout_seconds: u64,
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
    #[arg(long, default_value = "build")]
    opencode_agent: Option<String>,
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
        Command::Request(args) => request(args),
        Command::Review(args) => review(*args),
        Command::Render(args) => render(args),
    }
}

fn request(args: RequestArgs) -> Result<()> {
    let (request, out) = match args.command {
        RequestCommand::GitRange(args) => {
            let out = args.out;
            let request = build_git_range_request(&GitRangeRequestOptions {
                repo_path: args.repo_path,
                base: args.base,
                head: args.head,
                title: args.title,
                description: args.description,
                repo: args.repo,
                common: RequestOptions {
                    request_id: args.request_id,
                    instructions: args.instructions,
                    allowed_env: args.allowed_env,
                    timeout_ms: args.timeout_seconds * 1000,
                },
            })?;
            (request, out)
        }
        RequestCommand::Pr(args) => {
            let out = args.out;
            let request = build_pull_request(&PullRequestOptions {
                number: args.number,
                repo: args.repo,
                head_workspace: args.head_workspace,
                common: RequestOptions {
                    request_id: args.request_id,
                    instructions: args.instructions,
                    allowed_env: args.allowed_env,
                    timeout_ms: args.timeout_seconds * 1000,
                },
            })?;
            (request, out)
        }
    };
    validate_request(&request)?;
    write_json(&out, &request)
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
        opencode_agent,
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
        opencode_agent,
        omp_binary,
        model,
        timeout,
        failure_transcript: transcript.clone(),
    };
    let run = review_harness.run(&request, &cwd)?;
    let plan_path = execution_plan.unwrap_or_else(|| sibling_path(&out, "execution_plan.json"));
    write_json(&plan_path, &run.execution_plan)?;
    if let Some(transcript_path) = &transcript {
        write_text(transcript_path, &run.transcript)?;
    }
    validate_artifact_for_request(&run.artifact, &request)?;

    write_json(&out, &run.artifact)?;
    if let Some(markdown) = markdown {
        write_text(&markdown, &render_markdown(&run.artifact))?;
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
