use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use cerberus::harness::{
    ExecutionPlan, FixtureSubstrateConfig, HarnessKind, OmpSubstrateConfig, OpenCodeSubstrateConfig,
};
use cerberus::kernel::{ReviewKernel, ReviewRun, ReviewSubstrate, RunPolicy};
use cerberus::post::{build_post_plan, trusted_lifecycle, GithubClient, SummaryTarget};
use cerberus::producer::{build_crucible_producer_manifest, CrucibleProducerManifestInput};
use cerberus::receipt::{build_review_receipt_bundle, ReceiptBundleInput};
use cerberus::request::{
    build_git_range_request, build_pull_request, fetch_pull_request_head_sha,
    GitRangeRequestOptions, PullRequestOptions, RequestOptions,
};
use cerberus::schema::{RuntimeTarget, Verdict};
use cerberus::{
    render_markdown, validate_artifact_for_request, validate_request, ReviewArtifact, ReviewRequest,
};
use clap::{ArgGroup, Args, Parser, Subcommand, ValueEnum};

/// Maps a review verdict to a process exit code so a calling agent can gate on
/// it. A blocking verdict (exit 1) is a *successful* review that found issues —
/// distinct from a Cerberus error (exit 2), which means no valid review at all.
#[derive(Debug, Clone, Copy, Default, ValueEnum, PartialEq, Eq)]
enum FailOn {
    /// Never block on the verdict; exit 0 on any valid artifact (back-compat).
    #[default]
    None,
    /// Block (exit 1) when the verdict is WARN or FAIL.
    Warn,
    /// Block (exit 1) when the verdict is FAIL.
    Fail,
}

fn is_blocking(verdict: &Verdict, fail_on: FailOn) -> bool {
    match fail_on {
        FailOn::None => false,
        FailOn::Warn => matches!(verdict, Verdict::Warn | Verdict::Fail),
        FailOn::Fail => matches!(verdict, Verdict::Fail),
    }
}

/// Exit code for a review that produced a valid artifact: 1 if the verdict is
/// blocking under `fail_on`, else 0. Cerberus errors never reach here — they
/// propagate as `Err` and `main` maps them to exit 2.
fn verdict_exit_code(verdict: &Verdict, fail_on: FailOn) -> ExitCode {
    if is_blocking(verdict, fail_on) {
        ExitCode::from(1)
    } else {
        ExitCode::SUCCESS
    }
}

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
    ReviewDiff(Box<ReviewDiffArgs>),
    ReviewPr(Box<ReviewPrArgs>),
    Render(RenderArgs),
    /// Run the Cerberus MCP server over stdio.
    Mcp,
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

/// Substrate selection flags shared by every command that runs a review
/// (`review`, `review-pr`, `review-diff`). Flattened into each so the CLI
/// surface stays identical while the declaration lives in one place.
#[derive(Debug, Args)]
struct SubstrateArgs {
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
}

#[derive(Debug, Args)]
struct ReviewArgs {
    #[arg(long)]
    request: PathBuf,
    #[arg(long)]
    out: PathBuf,
    #[arg(long)]
    markdown: Option<PathBuf>,
    #[command(flatten)]
    substrate: SubstrateArgs,
    #[arg(long)]
    cwd: Option<PathBuf>,
    #[arg(long)]
    timeout_seconds: Option<u64>,
    #[arg(long)]
    execution_plan: Option<PathBuf>,
    #[arg(long)]
    transcript: Option<PathBuf>,
    #[arg(long)]
    receipt_bundle: Option<PathBuf>,
    /// Write a Crucible producer manifest sidecar. Requires --receipt-bundle and contains no scores.
    #[arg(long)]
    producer_manifest: Option<PathBuf>,
    #[arg(long = "allow-env")]
    allowed_env: Vec<String>,
    #[arg(long, value_enum, default_value_t = FailOn::None)]
    fail_on: FailOn,
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
    /// Read the explicit GitHub token from this file. Required unless --gh-token-env is used.
    #[arg(long)]
    gh_token_file: Option<PathBuf>,
    /// Read the explicit GitHub token from this named env var. Required unless --gh-token-file is used.
    #[arg(long)]
    gh_token_env: Option<String>,
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
    #[command(flatten)]
    substrate: SubstrateArgs,
    #[arg(long)]
    cwd: Option<PathBuf>,
    #[arg(long)]
    receipt_bundle: Option<PathBuf>,
}

#[derive(Debug, Args)]
struct RenderArgs {
    #[arg(long)]
    artifact: PathBuf,
    #[arg(long)]
    markdown: PathBuf,
}

/// Agent-native: build a git-range request and review it in one command, with
/// no GitHub and no token. The review is printed to stdout (Markdown, or the raw
/// artifact under `--json`); the exit code gates on the verdict via `--fail-on`.
#[derive(Debug, Args)]
struct ReviewDiffArgs {
    #[arg(long, default_value = ".")]
    repo_path: PathBuf,
    #[arg(long)]
    base: String,
    #[arg(long, default_value = "HEAD")]
    head: String,
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
    #[command(flatten)]
    substrate: SubstrateArgs,
    #[arg(long, value_enum, default_value_t = FailOn::None)]
    fail_on: FailOn,
    /// Also write the artifact JSON to this path (still printed to stdout).
    #[arg(long)]
    out: Option<PathBuf>,
    /// Also write the rendered Markdown to this path.
    #[arg(long)]
    markdown: Option<PathBuf>,
    /// Print the raw ReviewArtifact.v1 JSON to stdout instead of Markdown.
    #[arg(long)]
    json: bool,
}

fn main() -> ExitCode {
    match run() {
        Ok(code) => code,
        // Any error means Cerberus produced no valid review: exit 2, distinct
        // from a blocking verdict (exit 1). Preserve the anyhow Debug chain so
        // the stderr messages callers/verify.sh match on are unchanged.
        Err(err) => {
            eprintln!("Error: {err:?}");
            ExitCode::from(2)
        }
    }
}

fn run() -> Result<ExitCode> {
    let cli = Cli::parse();
    match cli.command {
        Command::Request(args) => request(*args).map(|()| ExitCode::SUCCESS),
        Command::Review(args) => review(*args),
        Command::ReviewDiff(args) => review_diff(*args),
        Command::ReviewPr(args) => review_pr(*args).map(|()| ExitCode::SUCCESS),
        Command::Render(args) => render(args).map(|()| ExitCode::SUCCESS),
        Command::Mcp => cerberus::mcp::run_stdio().map(|()| ExitCode::SUCCESS),
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
                gh_token: None,
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

fn review_substrate(args: SubstrateArgs) -> Result<ReviewSubstrate> {
    let SubstrateArgs {
        harness,
        fixture_output,
        opencode_binary,
        opencode_attach,
        opencode_agent,
        omp_binary,
        model,
    } = args;
    match harness {
        HarnessKind::Fixture => {
            let output = fixture_output
                .ok_or_else(|| anyhow!("--fixture-output is required for fixture harness"))?;
            Ok(ReviewSubstrate::Fixture(FixtureSubstrateConfig { output }))
        }
        HarnessKind::Opencode => Ok(ReviewSubstrate::Opencode(OpenCodeSubstrateConfig {
            binary: opencode_binary,
            attach: opencode_attach,
            agent: opencode_agent,
            model,
        })),
        HarnessKind::Omp => Ok(ReviewSubstrate::Omp(OmpSubstrateConfig {
            binary: omp_binary,
            model,
        })),
    }
}

fn review(args: ReviewArgs) -> Result<ExitCode> {
    let ReviewArgs {
        request,
        out,
        markdown,
        substrate,
        cwd,
        timeout_seconds,
        execution_plan,
        transcript,
        receipt_bundle,
        producer_manifest,
        allowed_env,
        fail_on,
    } = args;
    if producer_manifest.is_some() && receipt_bundle.is_none() {
        return Err(anyhow!(
            "review --producer-manifest requires --receipt-bundle so the packet includes redacted receipt metadata"
        ));
    }
    if let Some(receipt_bundle) = &receipt_bundle {
        remove_file_if_exists(receipt_bundle)?;
    }
    if let Some(producer_manifest) = &producer_manifest {
        remove_file_if_exists(producer_manifest)?;
    }
    let mut request = read_json::<ReviewRequest>(&request)?;
    extend_review_allowed_env(&mut request, allowed_env);
    validate_request(&request)?;
    let cwd = cwd.unwrap_or(std::env::current_dir().context("read current directory")?);
    let transcript_path = transcript.or_else(|| {
        receipt_bundle
            .as_ref()
            .map(|_| sibling_path(&out, "transcript.txt"))
    });
    let timeout = timeout_seconds
        .map(Duration::from_secs)
        .unwrap_or_else(|| Duration::from_millis(request.policy.timeout_ms));
    let substrate = review_substrate(substrate)?;
    require_child_env_for_substrate(&request, &substrate)?;
    let kernel = ReviewKernel::new(substrate);
    let run_policy = RunPolicy {
        cwd,
        timeout,
        failure_transcript: transcript_path.clone(),
    };
    let run = kernel.review(&request, &run_policy)?;
    let plan_path = execution_plan.unwrap_or_else(|| sibling_path(&out, "execution_plan.json"));
    write_json(&plan_path, &run.execution_plan)?;
    if let Some(transcript_path) = &transcript_path {
        write_text(transcript_path, &run.transcript)?;
    }
    write_json(&out, &run.artifact)?;
    let validation_result = validate_artifact_for_request(&run.artifact, &request);
    let receipt_bundle_value = if let Some(receipt_bundle) = &receipt_bundle {
        Some(write_review_receipt_bundle(
            receipt_bundle,
            &request,
            &run,
            &out,
            transcript_path.as_deref(),
            Some(&plan_path),
            validation_result.is_err(),
        )?)
    } else {
        None
    };
    validation_result?;

    if let Some(producer_manifest) = &producer_manifest {
        let receipt_bundle_path = receipt_bundle
            .as_ref()
            .expect("--producer-manifest requires --receipt-bundle");
        let receipt_bundle_value = receipt_bundle_value
            .as_ref()
            .expect("receipt bundle was written before producer manifest");
        let manifest = build_crucible_producer_manifest(CrucibleProducerManifestInput {
            request: &request,
            artifact: &run.artifact,
            receipt_bundle: receipt_bundle_value,
            receipt_bundle_uri: receipt_bundle_path.display().to_string(),
        })?;
        write_json(producer_manifest, &manifest)?;
    }

    if let Some(markdown) = markdown {
        write_text(&markdown, &render_markdown(&run.artifact))?;
    }
    Ok(verdict_exit_code(&run.artifact.verdict, fail_on))
}

fn extend_review_allowed_env(request: &mut ReviewRequest, allowed_env: Vec<String>) {
    for key in allowed_env {
        if !request
            .policy
            .allowed_env
            .iter()
            .any(|existing| existing == &key)
        {
            request.policy.allowed_env.push(key);
        }
    }
}

fn require_child_env_for_substrate(
    request: &ReviewRequest,
    substrate: &ReviewSubstrate,
) -> Result<()> {
    let ReviewSubstrate::Opencode(config) = substrate else {
        return Ok(());
    };
    let Some(model) = config.model.as_deref() else {
        return Ok(());
    };
    if config.attach.is_some() || !model.starts_with("openrouter/") {
        return Ok(());
    }
    if request
        .policy
        .allowed_env
        .iter()
        .any(|key| key == "OPENROUTER_API_KEY")
    {
        return Ok(());
    }
    Err(anyhow!(
        "opencode OpenRouter model {model:?} requires OPENROUTER_API_KEY in Cerberus's scrubbed child environment; pass --allow-env OPENROUTER_API_KEY or include it in request.policy.allowed_env"
    ))
}

fn review_diff(args: ReviewDiffArgs) -> Result<ExitCode> {
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
    validate_request(&request)?;
    let cwd = std::env::current_dir().context("read current directory")?;
    let substrate = review_substrate(args.substrate)?;
    require_child_env_for_substrate(&request, &substrate)?;
    let kernel = ReviewKernel::new(substrate);
    let run_policy = RunPolicy {
        cwd,
        timeout: Duration::from_millis(request.policy.timeout_ms),
        failure_transcript: None,
    };
    let run = kernel.review(&request, &run_policy)?;
    validate_artifact_for_request(&run.artifact, &request)?;

    // Optional persistence; stdout stays the primary deliverable for the caller.
    if let Some(out) = &args.out {
        write_json(out, &run.artifact)?;
    }
    let markdown = render_markdown(&run.artifact);
    if let Some(path) = &args.markdown {
        write_text(path, &markdown)?;
    }
    if args.json {
        println!("{}", serde_json::to_string_pretty(&run.artifact)?);
    } else {
        print!("{markdown}");
    }
    Ok(verdict_exit_code(&run.artifact.verdict, args.fail_on))
}

fn review_pr(args: ReviewPrArgs) -> Result<()> {
    let request_path = args.out_dir.join("request.json");
    let artifact_path = args.out_dir.join("artifact.json");
    let markdown_path = args.out_dir.join("review.md");
    let execution_plan_path = args.out_dir.join("execution_plan.json");
    let transcript_path = args.out_dir.join("transcript.txt");
    let receipt_bundle_path = args
        .receipt_bundle
        .clone()
        .unwrap_or_else(|| args.out_dir.join("receipt-bundle.json"));
    let post_plan_path = args.out_dir.join("post-plan.json");
    let post_result_path = args.out_dir.join("post-result.json");
    clean_review_pr_post_receipts(&post_plan_path, &post_result_path)?;
    remove_file_if_exists(&receipt_bundle_path)?;
    let github_token =
        resolve_github_token(args.gh_token_file.as_deref(), args.gh_token_env.as_deref())?;
    let gh_binary = args.gh_binary.clone();

    let request = build_pull_request(&PullRequestOptions {
        number: args.number,
        repo: Some(args.repo.clone()),
        gh_binary: gh_binary.clone(),
        gh_token: Some(github_token.clone()),
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
    let head_sha = request
        .change
        .head_sha
        .as_deref()
        .ok_or_else(|| anyhow!("review-pr requires request.change.head_sha"))?
        .to_string();
    ensure_pr_head_unchanged(
        args.number,
        &args.repo,
        &gh_binary,
        Some(&github_token),
        &head_sha,
    )?;

    let cwd = args
        .cwd
        .unwrap_or(std::env::current_dir().context("read current directory")?);
    let substrate = review_substrate(args.substrate)?;
    require_child_env_for_substrate(&request, &substrate)?;
    let kernel = ReviewKernel::new(substrate);
    let run_policy = RunPolicy {
        cwd,
        timeout: Duration::from_millis(request.policy.timeout_ms),
        failure_transcript: Some(transcript_path.clone()),
    };
    let run = kernel.review(&request, &run_policy)?;
    write_json(&execution_plan_path, &run.execution_plan)?;
    write_text(&transcript_path, &run.transcript)?;
    write_json(&artifact_path, &run.artifact)?;
    let validation_result = validate_artifact_for_request(&run.artifact, &request);
    ensure_pr_head_unchanged(
        args.number,
        &args.repo,
        &gh_binary,
        Some(&github_token),
        &head_sha,
    )?;
    if validation_result.is_err() {
        write_review_receipt_bundle(
            &receipt_bundle_path,
            &request,
            &run,
            &artifact_path,
            Some(&transcript_path),
            Some(&execution_plan_path),
            true,
        )?;
        validation_result?;
    }
    if !trusted_lifecycle(&run.artifact) {
        write_review_receipt_bundle(
            &receipt_bundle_path,
            &request,
            &run,
            &artifact_path,
            Some(&transcript_path),
            Some(&execution_plan_path),
            false,
        )?;
        write_text(&markdown_path, &render_markdown(&run.artifact))?;
        return Err(anyhow!(
            "review artifact lifecycle {:?} is not trusted for posting",
            run.artifact.lifecycle_state
        ));
    }
    write_text(&markdown_path, &render_markdown(&run.artifact))?;

    let mut github = GithubClient::new(gh_binary.clone());
    github = github.with_token(github_token.clone());
    let existing =
        github.read_existing_state(&args.repo, args.number, &head_sha, args.summary_target)?;
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
        ensure_pr_head_unchanged(
            args.number,
            &args.repo,
            &gh_binary,
            Some(&github_token),
            &post_plan.head_sha,
        )?;
        write_review_receipt_bundle(
            &receipt_bundle_path,
            &request,
            &run,
            &artifact_path,
            Some(&transcript_path),
            Some(&execution_plan_path),
            false,
        )?;
        let result = github.apply_plan(&post_plan)?;
        write_json(&post_result_path, &result)?;
    } else {
        write_review_receipt_bundle(
            &receipt_bundle_path,
            &request,
            &run,
            &artifact_path,
            Some(&transcript_path),
            Some(&execution_plan_path),
            false,
        )?;
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

fn resolve_github_token(token_file: Option<&Path>, token_env: Option<&str>) -> Result<String> {
    match (token_file, token_env) {
        (Some(_), Some(_)) => Err(anyhow!(
            "review-pr accepts exactly one explicit GitHub token source: --gh-token-file or --gh-token-env"
        )),
        (Some(path), None) => {
            let raw = fs::read_to_string(path)
                .with_context(|| format!("read GitHub token file {}", path.display()))?;
            let token = raw.trim_end_matches(['\r', '\n']).to_string();
            if token.trim().is_empty() {
                return Err(anyhow!(
                    "GitHub token file {} is empty; refusing to read or post",
                    path.display()
                ));
            }
            Ok(token)
        }
        (None, Some(var)) => {
            let token = std::env::var(var)
                .with_context(|| format!("read explicit GitHub token env var {var}"))?;
            if token.trim().is_empty() {
                return Err(anyhow!(
                    "explicit GitHub token env var {var} is empty; refusing to read or post"
                ));
            }
            Ok(token)
        }
        (None, None) => Err(anyhow!(
            "review-pr requires an explicit GitHub token via --gh-token-file <path> or --gh-token-env <VAR>; ambient gh auth is refused for GitHub reads and posting"
        )),
    }
}

fn ensure_pr_head_unchanged(
    number: u64,
    repo: &str,
    gh_binary: &str,
    gh_token: Option<&str>,
    expected_head_sha: &str,
) -> Result<()> {
    let current = fetch_pull_request_head_sha(number, Some(repo), gh_binary, gh_token)?;
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

fn write_review_receipt_bundle(
    path: &Path,
    request: &ReviewRequest,
    run: &ReviewRun,
    artifact_path: &Path,
    transcript_path: Option<&Path>,
    execution_plan_path: Option<&Path>,
    validation_failed: bool,
) -> Result<cerberus::ReviewReceiptBundle> {
    let bundle = build_review_receipt_bundle(ReceiptBundleInput {
        request,
        artifact: &run.artifact,
        harness: &run.execution_plan.harness,
        telemetry: &run.telemetry,
        transcript: &run.transcript,
        artifact_uri: artifact_path.display().to_string(),
        transcript_uri: transcript_path.map(|path| path.display().to_string()),
        execution_plan_uri: execution_plan_path.map(|path| path.display().to_string()),
        validation_failed,
    })?;
    write_json(path, &bundle)?;
    Ok(bundle)
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

#[cfg(test)]
mod tests {
    use super::*;

    const ALL_VERDICTS: [Verdict; 4] = [Verdict::Pass, Verdict::Warn, Verdict::Fail, Verdict::Skip];

    #[test]
    fn fail_on_none_never_blocks() {
        for verdict in ALL_VERDICTS {
            assert!(!is_blocking(&verdict, FailOn::None));
        }
    }

    #[test]
    fn fail_on_fail_blocks_only_fail() {
        assert!(is_blocking(&Verdict::Fail, FailOn::Fail));
        for verdict in [Verdict::Pass, Verdict::Warn, Verdict::Skip] {
            assert!(!is_blocking(&verdict, FailOn::Fail));
        }
    }

    #[test]
    fn fail_on_warn_blocks_warn_and_fail() {
        assert!(is_blocking(&Verdict::Warn, FailOn::Warn));
        assert!(is_blocking(&Verdict::Fail, FailOn::Warn));
        assert!(!is_blocking(&Verdict::Pass, FailOn::Warn));
        // SKIP means "could not review", not "blocking".
        assert!(!is_blocking(&Verdict::Skip, FailOn::Warn));
    }

    #[test]
    fn review_allow_env_override_extends_request_policy() {
        let request_path =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("fixtures/requests/diff-only.json");
        let mut request: ReviewRequest = read_json(&request_path).expect("fixture request loads");

        extend_review_allowed_env(
            &mut request,
            vec![
                "OPENROUTER_API_KEY".to_string(),
                "OPENROUTER_API_KEY".to_string(),
                "CERBERUS_RUNTIME_FLAG".to_string(),
            ],
        );

        assert_eq!(
            request.policy.allowed_env,
            vec![
                "OPENROUTER_API_KEY".to_string(),
                "CERBERUS_RUNTIME_FLAG".to_string()
            ],
            "review --allow-env should augment a request file without duplicating names"
        );
    }

    #[test]
    fn openrouter_model_without_allowed_key_is_a_clear_preflight_error() {
        let request_path =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("fixtures/requests/diff-only.json");
        let request: ReviewRequest = read_json(&request_path).expect("fixture request loads");
        let substrate = ReviewSubstrate::Opencode(OpenCodeSubstrateConfig {
            binary: "opencode".to_string(),
            attach: None,
            agent: Some("build".to_string()),
            model: Some("openrouter/z-ai/glm-5.2".to_string()),
        });

        let err = require_child_env_for_substrate(&request, &substrate).unwrap_err();
        assert!(
            err.to_string().contains("--allow-env OPENROUTER_API_KEY"),
            "error should name the concrete fix: {err}"
        );
    }

    #[test]
    fn openrouter_model_with_allowed_key_passes_preflight() {
        let request_path =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("fixtures/requests/diff-only.json");
        let mut request: ReviewRequest = read_json(&request_path).expect("fixture request loads");
        extend_review_allowed_env(&mut request, vec!["OPENROUTER_API_KEY".to_string()]);
        let substrate = ReviewSubstrate::Opencode(OpenCodeSubstrateConfig {
            binary: "opencode".to_string(),
            attach: None,
            agent: Some("build".to_string()),
            model: Some("openrouter/z-ai/glm-5.2".to_string()),
        });

        require_child_env_for_substrate(&request, &substrate).unwrap();
    }

    // The ExitCode mapping (blocking -> 1, clean -> 0, error -> 2) is proven
    // end-to-end by the exit-code matrix in scripts/verify.sh; ExitCode is not
    // PartialEq, so it cannot be asserted here.
}
