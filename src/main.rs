use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use cerberus::harness::{ExecutionPlan, HarnessKind, ReviewHarness};
use cerberus::post::{build_post_plan, trusted_lifecycle, GithubClient, SummaryTarget};
use cerberus::request::{
    build_git_range_request, build_pull_request, fetch_pull_request_head_sha,
    GitRangeRequestOptions, PullRequestOptions, RequestOptions,
};
use cerberus::schema::RuntimeTarget;
use cerberus::{
    render_markdown, validate_artifact_for_request, validate_request, ReviewArtifact, ReviewRequest,
};
use clap::{ArgGroup, Args, Parser, Subcommand};

#[derive(Debug, Parser)]
#[command(name = "cerberus")]
#[command(about = "Context-adaptive code review runner")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    Request(Box<RequestArgs>),
    Review(Box<ReviewArgs>),
    ReviewPr(Box<ReviewPrArgs>),
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
    base_workspace: Option<PathBuf>,
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
    #[arg(long = "local-runtime-command")]
    local_runtime_commands: Vec<String>,
    #[arg(long)]
    allow_local_runtime: bool,
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
    #[arg(long, default_value = "gh")]
    gh_binary: String,
    #[arg(long)]
    head_workspace: Option<PathBuf>,
    #[arg(long)]
    base_workspace: Option<PathBuf>,
    #[arg(long)]
    request_id: Option<String>,
    #[arg(long = "instruction")]
    instructions: Vec<String>,
    #[arg(long = "local-runtime-command")]
    local_runtime_commands: Vec<String>,
    #[arg(long)]
    allow_local_runtime: bool,
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
#[command(group(
    ArgGroup::new("posting-mode")
        .args(["dry_run", "post"])
        .multiple(false)
))]
struct ReviewPrArgs {
    #[arg(long)]
    number: u64,
    #[arg(long)]
    repo: String,
    #[arg(long, default_value = "target/cerberus/review-pr")]
    out_dir: PathBuf,
    #[arg(long)]
    dry_run: bool,
    #[arg(long)]
    post: bool,
    #[arg(long, value_enum, default_value_t = SummaryTarget::CheckRun)]
    summary_target: SummaryTarget,
    #[arg(long, default_value = "gh")]
    gh_binary: String,
    #[arg(long)]
    head_workspace: Option<PathBuf>,
    #[arg(long)]
    base_workspace: Option<PathBuf>,
    #[arg(long)]
    request_id: Option<String>,
    #[arg(long = "instruction")]
    instructions: Vec<String>,
    #[arg(long = "local-runtime-command")]
    local_runtime_commands: Vec<String>,
    #[arg(long)]
    allow_local_runtime: bool,
    #[arg(long = "allow-env")]
    allowed_env: Vec<String>,
    #[arg(long, default_value_t = 120)]
    timeout_seconds: u64,
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
        Command::Request(args) => request(*args),
        Command::Review(args) => review(*args),
        Command::ReviewPr(args) => review_pr(*args),
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
                base_workspace: args.base_workspace,
                title: args.title,
                description: args.description,
                repo: args.repo,
                common: RequestOptions {
                    request_id: args.request_id,
                    instructions: args.instructions,
                    local_runtime: runtime_targets(args.local_runtime_commands),
                    allow_local_runtime: args.allow_local_runtime,
                    allowed_env: args.allowed_env,
                    timeout_ms: timeout_ms(args.timeout_seconds)?,
                },
            })?;
            (request, out)
        }
        RequestCommand::Pr(args) => {
            let out = args.out;
            let request = build_pull_request(&PullRequestOptions {
                number: args.number,
                repo: args.repo,
                gh_binary: args.gh_binary,
                head_workspace: args.head_workspace,
                base_workspace: args.base_workspace,
                common: RequestOptions {
                    request_id: args.request_id,
                    instructions: args.instructions,
                    local_runtime: runtime_targets(args.local_runtime_commands),
                    allow_local_runtime: args.allow_local_runtime,
                    allowed_env: args.allowed_env,
                    timeout_ms: timeout_ms(args.timeout_seconds)?,
                },
            })?;
            (request, out)
        }
    };
    validate_request(&request)?;
    write_json(&out, &request)
}

fn timeout_ms(timeout_seconds: u64) -> Result<u64> {
    timeout_seconds
        .checked_mul(1000)
        .ok_or_else(|| anyhow!("timeout seconds {timeout_seconds} overflows milliseconds"))
}

fn runtime_targets(commands: Vec<String>) -> Vec<RuntimeTarget> {
    commands
        .into_iter()
        .map(|command| RuntimeTarget {
            kind: "command".to_string(),
            command,
            args: Vec::new(),
            cwd: None,
        })
        .collect()
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

fn review_pr(args: ReviewPrArgs) -> Result<()> {
    let request_path = args.out_dir.join("request.json");
    let artifact_path = args.out_dir.join("artifact.json");
    let markdown_path = args.out_dir.join("review.md");
    let execution_plan_path = args.out_dir.join("execution_plan.json");
    let transcript_path = args.out_dir.join("transcript.txt");
    let post_plan_path = args.out_dir.join("post-plan.json");
    let post_result_path = args.out_dir.join("post-result.json");
    clean_review_pr_post_receipts(&post_plan_path, &post_result_path)?;
    let gh_binary = args.gh_binary.clone();

    let request = build_pull_request(&PullRequestOptions {
        number: args.number,
        repo: Some(args.repo.clone()),
        gh_binary: gh_binary.clone(),
        head_workspace: args.head_workspace,
        base_workspace: args.base_workspace,
        common: RequestOptions {
            request_id: args.request_id,
            instructions: args.instructions,
            local_runtime: runtime_targets(args.local_runtime_commands),
            allow_local_runtime: args.allow_local_runtime,
            allowed_env: args.allowed_env,
            timeout_ms: timeout_ms(args.timeout_seconds)?,
        },
    })?;
    validate_request(&request)?;
    write_json(&request_path, &request)?;

    let cwd = args
        .cwd
        .unwrap_or(std::env::current_dir().context("read current directory")?);
    let review_harness = ReviewHarness {
        kind: args.harness,
        fixture_output: args.fixture_output,
        opencode_binary: args.opencode_binary,
        opencode_attach: args.opencode_attach,
        opencode_agent: args.opencode_agent,
        omp_binary: args.omp_binary,
        model: args.model,
        timeout: Duration::from_millis(request.policy.timeout_ms),
        failure_transcript: Some(transcript_path.clone()),
    };
    let run = review_harness.run(&request, &cwd)?;
    write_json(&execution_plan_path, &run.execution_plan)?;
    write_text(&transcript_path, &run.transcript)?;
    validate_artifact_for_request(&run.artifact, &request)?;
    if !trusted_lifecycle(&run.artifact) {
        write_json(&artifact_path, &run.artifact)?;
        write_text(&markdown_path, &render_markdown(&run.artifact))?;
        return Err(anyhow!(
            "review artifact lifecycle {:?} is not trusted for posting",
            run.artifact.lifecycle_state
        ));
    }
    write_json(&artifact_path, &run.artifact)?;
    write_text(&markdown_path, &render_markdown(&run.artifact))?;

    let head_sha = request
        .change
        .head_sha
        .as_deref()
        .ok_or_else(|| anyhow!("review-pr requires request.change.head_sha"))?;
    ensure_pr_head_unchanged(args.number, &args.repo, &gh_binary, head_sha)?;

    let github = GithubClient::new(gh_binary.clone());
    let existing =
        github.read_existing_state(&args.repo, args.number, head_sha, args.summary_target)?;
    let post_plan = build_post_plan(
        &request,
        &run.artifact,
        &args.repo,
        args.number,
        args.summary_target,
        &existing,
    )?;
    write_json(&post_plan_path, &post_plan)?;

    if args.post {
        ensure_pr_head_unchanged(args.number, &args.repo, &gh_binary, &post_plan.head_sha)?;
        let result = github.apply_plan(&post_plan)?;
        write_json(&post_result_path, &result)?;
    } else {
        println!("{}", serde_json::to_string_pretty(&post_plan)?);
    }

    Ok(())
}

fn clean_review_pr_post_receipts(post_plan: &Path, post_result: &Path) -> Result<()> {
    remove_file_if_exists(post_plan)?;
    remove_file_if_exists(post_result)
}

fn remove_file_if_exists(path: &Path) -> Result<()> {
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(err) => Err(err).with_context(|| format!("remove stale {}", path.display())),
    }
}

fn ensure_pr_head_unchanged(
    number: u64,
    repo: &str,
    gh_binary: &str,
    expected_head_sha: &str,
) -> Result<()> {
    let current = fetch_pull_request_head_sha(number, Some(repo), gh_binary)?;
    if current != expected_head_sha {
        return Err(anyhow!(
            "pull request #{number} head moved from {expected_head_sha} to {current}; refusing to post stale Cerberus output"
        ));
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
