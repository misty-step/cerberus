use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use cerberus::container::ContainerOpencodeSubstrateConfig;
use cerberus::harness::{
    ExecutionPlan, FixtureSubstrateConfig, HarnessKind, OmpSubstrateConfig, OpenCodeSubstrateConfig,
};
use cerberus::kernel::{ReviewKernel, ReviewRun, ReviewSubstrate, RunPolicy};
use cerberus::openrouter_keys::{mint_review_key, ProvisioningClient, ScopedKeyGuard};
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
use uuid::Uuid;

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
    /// Build a ReviewRequest.v1 without running a review.
    Request(Box<RequestArgs>),
    /// Run a review from an existing ReviewRequest.v1 file.
    Review(Box<ReviewArgs>),
    /// Build a request from a local git diff and review it in one command;
    /// no GitHub, no token.
    ReviewDiff(Box<ReviewDiffArgs>),
    /// Fetch a GitHub pull request, review it, and optionally post the
    /// result.
    ReviewPr(Box<ReviewPrArgs>),
    /// Render an existing ReviewArtifact.v1 to Markdown.
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
    /// Build a request from a local git base/head range.
    GitRange(GitRangeArgs),
    /// Build a request from a GitHub pull request (read-only, ambient `gh` auth).
    Pr(PullRequestArgs),
}

/// Build a `ReviewRequest.v1` from a local git base/head range, with no
/// GitHub and no token. Write it with `--out` for a later `review` command,
/// or use `review-diff` to build and review in one step.
#[derive(Debug, Args)]
struct GitRangeArgs {
    /// Git checkout to diff. Must be a real, non-bare repository.
    #[arg(long, default_value = ".")]
    repo_path: PathBuf,
    /// Base ref or sha the diff is computed against.
    #[arg(long)]
    base: String,
    /// Head ref or sha to diff. Defaults to the checkout's current HEAD.
    #[arg(long, default_value = "HEAD")]
    head: String,
    /// Write the built ReviewRequest.v1 JSON here.
    #[arg(long)]
    out: PathBuf,
    /// Grant `repo_base` context by pointing at a second checkout of the base
    /// ref. Without this, the request carries diff + repo_head context only.
    #[arg(long)]
    base_workspace: Option<PathBuf>,
    /// Human-readable change title recorded on the request.
    #[arg(long)]
    title: Option<String>,
    /// Longer change description recorded on the request.
    #[arg(long)]
    description: Option<String>,
    /// Explicit request id. Defaults to a generated id if omitted.
    #[arg(long)]
    request_id: Option<String>,
    /// `owner/name` slug recorded on the request source, for display only.
    #[arg(long)]
    repo: Option<String>,
    /// Extra reviewer instruction, repeatable. Appended to the request's
    /// instructions list in the order given.
    #[arg(long = "instruction")]
    instructions: Vec<String>,
    /// Local command the reviewer may run as a bounded runtime probe (e.g. a
    /// test suite), repeatable. Requires --allow-local-runtime.
    #[arg(long = "local-runtime-command")]
    local_runtime_commands: Vec<String>,
    /// Permit the local-runtime commands above to actually run. Without
    /// this, local-runtime-command entries are rejected at validation.
    #[arg(long)]
    allow_local_runtime: bool,
    /// Env var name the review substrate's child process may inherit,
    /// repeatable. Everything else is scrubbed from the child's environment.
    #[arg(long = "allow-env")]
    allowed_env: Vec<String>,
    /// Wall-clock budget for the review, in seconds.
    #[arg(long, default_value_t = 120)]
    timeout_seconds: u64,
}

/// Build a `ReviewRequest.v1` from a GitHub pull request via ambient `gh`
/// auth. Read-only: use `review-pr` instead if you also want to run and
/// post the review with an explicit token.
#[derive(Debug, Args)]
struct PullRequestArgs {
    /// Pull request number.
    #[arg(long)]
    number: u64,
    /// Write the built ReviewRequest.v1 JSON here.
    #[arg(long)]
    out: PathBuf,
    /// `owner/name` slug. Defaults to the repo `gh` resolves from the
    /// current directory.
    #[arg(long)]
    repo: Option<String>,
    /// `gh` binary, resolved from the trusted search path.
    #[arg(long, default_value = "gh")]
    gh_binary: String,
    /// Grant `repo_head` context by pointing at a checkout of the PR's head
    /// ref. Without this, the request carries diff context only.
    #[arg(long)]
    head_workspace: Option<PathBuf>,
    /// Grant `repo_base` context by pointing at a checkout of the PR's base
    /// ref. Requires --head-workspace.
    #[arg(long)]
    base_workspace: Option<PathBuf>,
    /// Explicit request id. Defaults to a generated id if omitted.
    #[arg(long)]
    request_id: Option<String>,
    /// Extra reviewer instruction, repeatable. Appended to the request's
    /// instructions list in the order given.
    #[arg(long = "instruction")]
    instructions: Vec<String>,
    /// Local command the reviewer may run as a bounded runtime probe (e.g. a
    /// test suite), repeatable. Requires --allow-local-runtime.
    #[arg(long = "local-runtime-command")]
    local_runtime_commands: Vec<String>,
    /// Permit the local-runtime commands above to actually run. Without
    /// this, local-runtime-command entries are rejected at validation.
    #[arg(long)]
    allow_local_runtime: bool,
    /// Env var name the review substrate's child process may inherit,
    /// repeatable. Everything else is scrubbed from the child's environment.
    #[arg(long = "allow-env")]
    allowed_env: Vec<String>,
    /// Wall-clock budget for the review, in seconds.
    #[arg(long, default_value_t = 120)]
    timeout_seconds: u64,
}

/// Substrate selection flags shared by every command that runs a review
/// (`review`, `review-pr`, `review-diff`). Flattened into each so the CLI
/// surface stays identical while the declaration lives in one place.
#[derive(Debug, Args)]
struct SubstrateArgs {
    /// Which review substrate runs the master reviewer: `opencode` (default,
    /// live model calls), `omp` (fallback), `fixture` (deterministic,
    /// tests/CI only — reads a canned artifact from --fixture-output), or
    /// `container-opencode` (opencode sandboxed for untrusted-PR review;
    /// backlog 013).
    #[arg(long, value_enum, default_value_t = HarnessKind::Opencode)]
    harness: HarnessKind,
    /// Path to a canned ReviewArtifact.v1 template the fixture substrate
    /// reads instead of calling a model. Required when --harness fixture.
    #[arg(long)]
    fixture_output: Option<PathBuf>,
    /// `opencode` binary, resolved from the trusted search path (or an
    /// absolute path). Used when --harness opencode.
    #[arg(long, default_value = "opencode")]
    opencode_binary: String,
    /// Attach to an existing opencode session id instead of starting a new
    /// one. Rarely needed outside interactive debugging.
    #[arg(long)]
    opencode_attach: Option<String>,
    /// opencode agent profile to run the review under.
    #[arg(long, default_value = "build")]
    opencode_agent: Option<String>,
    /// `omp` binary, resolved from the trusted search path. Used when
    /// --harness omp.
    #[arg(long, default_value = "omp")]
    omp_binary: String,
    /// Model id passed to the substrate (e.g. `openrouter/z-ai/glm-5.2`).
    /// Substrate-specific; unused by the fixture harness.
    #[arg(long)]
    model: Option<String>,
    /// `docker` (or a compatible CLI), resolved from the trusted search path,
    /// used only when `--harness container-opencode`.
    #[arg(long, default_value = "docker")]
    docker_binary: String,
    /// Base image `--harness container-opencode` runs the substrate binary
    /// inside. No image is built; a stock base image is used as-is.
    #[arg(long, default_value = cerberus::DEFAULT_CONTAINER_IMAGE)]
    container_image: String,
    /// Host path to the substrate executable bind-mounted read-only and
    /// exec'd inside the container in place of `--opencode-binary`. Required
    /// when `--harness container-opencode`.
    #[arg(long)]
    container_binary: Option<PathBuf>,
    /// Parent directory for the disposable per-run container host root.
    /// Defaults to the OS temp dir. Point this at a directory your Docker
    /// daemon can actually see if it runs inside a VM with a narrow mount
    /// allowlist (e.g. colima's default, which mounts only `$HOME`).
    #[arg(long)]
    container_host_root: Option<PathBuf>,
    /// The single `host:port` the container-opencode egress proxy allows
    /// `CONNECT` to. Every other host is unreachable from inside the
    /// sandbox, including for DNS resolution.
    #[arg(long, default_value = cerberus::DEFAULT_EGRESS_ALLOW_HOST)]
    container_egress_allow_host: String,
    /// Age past which the orphan sweeper removes a stale container-opencode
    /// container/network left by a crashed prior run, before creating this
    /// run's own resources.
    #[arg(long, default_value_t = 1800)]
    container_orphan_sweep_seconds: u64,
}

/// Scoped-ephemeral-key flags (backlog 013 M1), flattened into every command
/// that runs a review. When `--openrouter-scoped-key` is set, Cerberus mints
/// a per-review OpenRouter key capped at `--openrouter-key-limit-usd` instead
/// of forwarding a long-lived OPENROUTER_API_KEY into a substrate that also
/// has webfetch/bash access — the confirmed exfil path for a prompt-injected
/// untrusted-PR review. Off by default; trusted self-review is unaffected.
#[derive(Debug, Args)]
struct ScopedKeyArgs {
    /// Mint a per-review, USD-capped OpenRouter key instead of forwarding a
    /// long-lived OPENROUTER_API_KEY into the substrate. Requires
    /// --openrouter-provisioning-key-file or -env.
    #[arg(long)]
    openrouter_scoped_key: bool,
    /// Read the OpenRouter provisioning (management) key from this file.
    /// Required unless --openrouter-provisioning-key-env is used.
    #[arg(long)]
    openrouter_provisioning_key_file: Option<PathBuf>,
    /// Read the OpenRouter provisioning (management) key from this named env
    /// var. Required unless --openrouter-provisioning-key-file is used.
    #[arg(long)]
    openrouter_provisioning_key_env: Option<String>,
    /// USD spend cap on the minted key.
    #[arg(long, default_value_t = 5.0)]
    openrouter_key_limit_usd: f64,
    /// Age past which the orphan sweeper revokes a stale review-tagged key
    /// left by a crashed prior run, before minting a fresh one.
    #[arg(long, default_value_t = 1800)]
    openrouter_orphan_sweep_seconds: u64,
}

/// Run a review from an existing `ReviewRequest.v1` file (built by `request`
/// or `review-diff`, or hand-authored) and write a `ReviewArtifact.v1`.
#[derive(Debug, Args)]
struct ReviewArgs {
    /// ReviewRequest.v1 JSON to review.
    #[arg(long)]
    request: PathBuf,
    /// Write the ReviewArtifact.v1 JSON here.
    #[arg(long)]
    out: PathBuf,
    /// Also write the rendered Markdown here.
    #[arg(long)]
    markdown: Option<PathBuf>,
    #[command(flatten)]
    substrate: SubstrateArgs,
    #[command(flatten)]
    scoped_key: ScopedKeyArgs,
    /// Working directory for a diff-only request's disposable packet
    /// workspace. Defaults to the current directory.
    #[arg(long)]
    cwd: Option<PathBuf>,
    /// Wall-clock budget for the review, in seconds. Defaults to the
    /// request's own `policy.timeout_ms`.
    #[arg(long)]
    timeout_seconds: Option<u64>,
    /// Write the substrate execution plan (command, args, env allowlist,
    /// workspace mode) here. Defaults to a sibling of --out.
    #[arg(long)]
    execution_plan: Option<PathBuf>,
    /// Write the raw substrate transcript here. Written automatically next
    /// to --receipt-bundle if that flag is set and this one is not.
    #[arg(long)]
    transcript: Option<PathBuf>,
    /// Write a redacted ReviewReceiptBundle.v1 here — request/artifact
    /// digests, telemetry, and validation outcome for downstream eval labs.
    #[arg(long)]
    receipt_bundle: Option<PathBuf>,
    /// Write a Crucible producer manifest sidecar. Requires --receipt-bundle and contains no scores.
    #[arg(long)]
    producer_manifest: Option<PathBuf>,
    /// Env var name the review substrate's child process may inherit,
    /// repeatable. Everything else is scrubbed from the child's environment.
    #[arg(long = "allow-env")]
    allowed_env: Vec<String>,
    /// Map the verdict to the process exit code: `none` (default) never
    /// blocks, `warn` blocks on WARN or FAIL, `fail` blocks only on FAIL. A
    /// blocking verdict exits 1; a Cerberus error (no valid artifact) always
    /// exits 2 regardless of this flag.
    #[arg(long, value_enum, default_value_t = FailOn::None)]
    fail_on: FailOn,
}

/// Fetch a GitHub pull request, run a review, and optionally post it. Reads
/// require an explicit token (--gh-token-file or --gh-token-env); ambient
/// `gh` auth is never used for reads or posting. Refuses to post if the PR's
/// head moved since the request was built.
#[derive(Debug, Args)]
#[command(group(
    ArgGroup::new("posting-mode")
        .args(["dry_run", "post"])
        .multiple(false)
))]
struct ReviewPrArgs {
    /// Pull request number.
    #[arg(long)]
    number: u64,
    /// `owner/name` slug.
    #[arg(long)]
    repo: String,
    /// Directory request/artifact/transcript/receipt/post-plan files are
    /// written under.
    #[arg(long, default_value = "target/cerberus/review-pr")]
    out_dir: PathBuf,
    /// Plan the post (summary + inline comments) and write post-plan.json
    /// without publishing anything. Mutually exclusive with --post.
    #[arg(long)]
    dry_run: bool,
    /// Publish the planned summary and inline comments to the pull request.
    /// Mutually exclusive with --dry-run.
    #[arg(long)]
    post: bool,
    /// Where the review summary is published: a GitHub Checks run
    /// (`check-run`, needs Checks-write) or a commit status
    /// (`status`, needs only Statuses-write — use this if Checks-write is
    /// denied).
    #[arg(long, value_enum, default_value_t = SummaryTarget::CheckRun)]
    summary_target: SummaryTarget,
    /// `gh` binary, resolved from the trusted search path.
    #[arg(long, default_value = "gh")]
    gh_binary: String,
    /// Read the explicit GitHub token from this file. Required unless --gh-token-env is used.
    #[arg(long)]
    gh_token_file: Option<PathBuf>,
    /// Read the explicit GitHub token from this named env var. Required unless --gh-token-file is used.
    #[arg(long)]
    gh_token_env: Option<String>,
    /// Grant `repo_head` context by pointing at a checkout of the PR's head
    /// ref. Without this, the request carries diff context only.
    #[arg(long)]
    head_workspace: Option<PathBuf>,
    /// Grant `repo_base` context by pointing at a checkout of the PR's base
    /// ref. Requires --head-workspace.
    #[arg(long)]
    base_workspace: Option<PathBuf>,
    /// Explicit request id. Defaults to a generated id if omitted.
    #[arg(long)]
    request_id: Option<String>,
    /// Extra reviewer instruction, repeatable. Appended to the request's
    /// instructions list in the order given.
    #[arg(long = "instruction")]
    instructions: Vec<String>,
    /// Local command the reviewer may run as a bounded runtime probe (e.g. a
    /// test suite), repeatable. Requires --allow-local-runtime.
    #[arg(long = "local-runtime-command")]
    local_runtime_commands: Vec<String>,
    /// Permit the local-runtime commands above to actually run. Without
    /// this, local-runtime-command entries are rejected at validation.
    #[arg(long)]
    allow_local_runtime: bool,
    /// Env var name the review substrate's child process may inherit,
    /// repeatable. Everything else is scrubbed from the child's environment.
    #[arg(long = "allow-env")]
    allowed_env: Vec<String>,
    /// Wall-clock budget for the review, in seconds.
    #[arg(long, default_value_t = 120)]
    timeout_seconds: u64,
    #[command(flatten)]
    substrate: SubstrateArgs,
    #[command(flatten)]
    scoped_key: ScopedKeyArgs,
    /// Working directory for a diff-only request's disposable packet
    /// workspace. Defaults to the current directory.
    #[arg(long)]
    cwd: Option<PathBuf>,
    /// Write a redacted ReviewReceiptBundle.v1 here instead of the default
    /// `<out-dir>/receipt-bundle.json`.
    #[arg(long)]
    receipt_bundle: Option<PathBuf>,
}

/// Render an existing ReviewArtifact.v1 to Markdown without re-running a
/// review.
#[derive(Debug, Args)]
struct RenderArgs {
    /// ReviewArtifact.v1 JSON to render.
    #[arg(long)]
    artifact: PathBuf,
    /// Write the rendered Markdown here.
    #[arg(long)]
    markdown: PathBuf,
}

/// Agent-native: build a git-range request and review it in one command, with
/// no GitHub and no token. The review is printed to stdout (Markdown, or the raw
/// artifact under `--json`); the exit code gates on the verdict via `--fail-on`.
#[derive(Debug, Args)]
struct ReviewDiffArgs {
    /// Git checkout to diff. Must be a real, non-bare repository.
    #[arg(long, default_value = ".")]
    repo_path: PathBuf,
    /// Base ref or sha the diff is computed against.
    #[arg(long)]
    base: String,
    /// Head ref or sha to diff. Defaults to the checkout's current HEAD.
    #[arg(long, default_value = "HEAD")]
    head: String,
    /// Grant `repo_base` context by pointing at a second checkout of the base
    /// ref. Without this, the request carries diff + repo_head context only.
    #[arg(long)]
    base_workspace: Option<PathBuf>,
    /// Human-readable change title recorded on the request.
    #[arg(long)]
    title: Option<String>,
    /// Longer change description recorded on the request.
    #[arg(long)]
    description: Option<String>,
    /// Explicit request id. Defaults to a generated id if omitted.
    #[arg(long)]
    request_id: Option<String>,
    /// `owner/name` slug recorded on the request source, for display only.
    #[arg(long)]
    repo: Option<String>,
    /// Extra reviewer instruction, repeatable. Appended to the request's
    /// instructions list in the order given.
    #[arg(long = "instruction")]
    instructions: Vec<String>,
    /// Local command the reviewer may run as a bounded runtime probe (e.g. a
    /// test suite), repeatable. Requires --allow-local-runtime.
    #[arg(long = "local-runtime-command")]
    local_runtime_commands: Vec<String>,
    /// Permit the local-runtime commands above to actually run. Without
    /// this, local-runtime-command entries are rejected at validation.
    #[arg(long)]
    allow_local_runtime: bool,
    /// Env var name the review substrate's child process may inherit,
    /// repeatable. Everything else is scrubbed from the child's environment.
    #[arg(long = "allow-env")]
    allowed_env: Vec<String>,
    /// Wall-clock budget for the review, in seconds.
    #[arg(long, default_value_t = 120)]
    timeout_seconds: u64,
    #[command(flatten)]
    substrate: SubstrateArgs,
    #[command(flatten)]
    scoped_key: ScopedKeyArgs,
    /// Map the verdict to the process exit code: `none` (default) never
    /// blocks, `warn` blocks on WARN or FAIL, `fail` blocks only on FAIL. A
    /// blocking verdict exits 1; a Cerberus error (no valid artifact) always
    /// exits 2 regardless of this flag.
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
        docker_binary,
        container_image,
        container_binary,
        container_host_root,
        container_egress_allow_host,
        container_orphan_sweep_seconds,
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
        HarnessKind::ContainerOpencode => {
            let binary_host_path = container_binary.ok_or_else(|| {
                anyhow!("--container-binary is required for container-opencode harness")
            })?;
            Ok(ReviewSubstrate::ContainerOpencode(
                ContainerOpencodeSubstrateConfig {
                    docker_binary,
                    image: container_image,
                    binary_host_path,
                    host_root_parent: container_host_root,
                    egress_allow_host: container_egress_allow_host,
                    orphan_sweep_max_age: Duration::from_secs(container_orphan_sweep_seconds),
                },
            ))
        }
    }
}

fn review(args: ReviewArgs) -> Result<ExitCode> {
    let ReviewArgs {
        request,
        out,
        markdown,
        substrate,
        scoped_key,
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
    let scoped_key_client = resolve_scoped_key_client(&scoped_key)?;
    let _scoped_key_guard =
        mint_scoped_openrouter_key(scoped_key_client.as_ref(), &mut request, &scoped_key)?;
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
    let reviewer_plan_path = reviewer_plan_path_for(&out);
    write_json(&plan_path, &run.execution_plan)?;
    write_json(&reviewer_plan_path, &run.reviewer_plan)?;
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
            ReviewReceiptPaths {
                artifact: &out,
                transcript: transcript_path.as_deref(),
                execution_plan: Some(&plan_path),
                reviewer_plan: Some(&reviewer_plan_path),
            },
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

/// Backlog 013 M1: build the provisioning client when `--openrouter-scoped-key`
/// is set, resolving its management key from an explicit file/env source only
/// (no ambient fallback, matching the house `--gh-token-file`/`--gh-token-env`
/// pattern). Returns `None` when scoped-key minting was not requested, so
/// callers fall back to the existing forwarded-`OPENROUTER_API_KEY` path
/// unchanged.
fn resolve_scoped_key_client(args: &ScopedKeyArgs) -> Result<Option<ProvisioningClient>> {
    if !args.openrouter_scoped_key {
        return Ok(None);
    }
    let key = resolve_openrouter_provisioning_key(
        args.openrouter_provisioning_key_file.as_deref(),
        args.openrouter_provisioning_key_env.as_deref(),
    )?;
    Ok(Some(ProvisioningClient::new(key)))
}

fn resolve_openrouter_provisioning_key(
    key_file: Option<&Path>,
    key_env: Option<&str>,
) -> Result<String> {
    match (key_file, key_env) {
        (Some(_), Some(_)) => Err(anyhow!(
            "--openrouter-scoped-key accepts exactly one explicit provisioning-key source: --openrouter-provisioning-key-file or --openrouter-provisioning-key-env"
        )),
        (Some(path), None) => {
            let raw = fs::read_to_string(path).with_context(|| {
                format!("read OpenRouter provisioning key file {}", path.display())
            })?;
            let key = raw.trim_end_matches(['\r', '\n']).to_string();
            if key.trim().is_empty() {
                return Err(anyhow!(
                    "OpenRouter provisioning key file {} is empty; refusing to mint scoped keys",
                    path.display()
                ));
            }
            Ok(key)
        }
        (None, Some(var)) => {
            let key = std::env::var(var)
                .with_context(|| format!("read explicit OpenRouter provisioning key env var {var}"))?;
            if key.trim().is_empty() {
                return Err(anyhow!(
                    "explicit OpenRouter provisioning key env var {var} is empty; refusing to mint scoped keys"
                ));
            }
            Ok(key)
        }
        (None, None) => Err(anyhow!(
            "--openrouter-scoped-key requires an explicit provisioning key via --openrouter-provisioning-key-file <path> or --openrouter-provisioning-key-env <VAR>; ambient env is refused"
        )),
    }
}

/// Mint a per-review OpenRouter key when a `client` was resolved, inject it
/// as `OPENROUTER_API_KEY` (shadowing any operator long-lived key already in
/// this process's env) for the child substrate to pick up via the normal
/// `allowed_env` forward path, and return the guard that revokes it. The
/// guard has a `Drop` impl, so holding it in an unused local keeps the key
/// alive exactly until the caller's function returns (success, error, or
/// panic) — see `ScopedKeyGuard` for why that is crash-safe within this
/// process. The mint-then-sweep sequence itself lives in
/// `cerberus::openrouter_keys::mint_review_key`, tested there against a mock
/// provisioning server; this function is just the CLI-specific glue (env
/// injection, request mutation).
fn mint_scoped_openrouter_key<'a>(
    client: Option<&'a ProvisioningClient>,
    request: &mut ReviewRequest,
    args: &ScopedKeyArgs,
) -> Result<Option<ScopedKeyGuard<'a>>> {
    let Some(client) = client else {
        return Ok(None);
    };
    let sweep_age = Duration::from_secs(args.openrouter_orphan_sweep_seconds);
    let tag = Uuid::new_v4().to_string();
    let minted = mint_review_key(client, &tag, args.openrouter_key_limit_usd, sweep_age)?;
    std::env::set_var("OPENROUTER_API_KEY", &minted.secret);
    extend_review_allowed_env(request, vec!["OPENROUTER_API_KEY".to_string()]);
    Ok(Some(ScopedKeyGuard::new(client, minted.hash)))
}

fn review_diff(args: ReviewDiffArgs) -> Result<ExitCode> {
    let mut request = build_git_range_request(&GitRangeRequestOptions {
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
    let scoped_key_client = resolve_scoped_key_client(&args.scoped_key)?;
    let _scoped_key_guard =
        mint_scoped_openrouter_key(scoped_key_client.as_ref(), &mut request, &args.scoped_key)?;
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
        write_json(&reviewer_plan_path_for(out), &run.reviewer_plan)?;
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
    let reviewer_plan_path = args.out_dir.join("reviewer_plan.json");
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

    let mut request = build_pull_request(&PullRequestOptions {
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
    let scoped_key_client = resolve_scoped_key_client(&args.scoped_key)?;
    let _scoped_key_guard =
        mint_scoped_openrouter_key(scoped_key_client.as_ref(), &mut request, &args.scoped_key)?;
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
    write_json(&reviewer_plan_path, &run.reviewer_plan)?;
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
            ReviewReceiptPaths {
                artifact: &artifact_path,
                transcript: Some(&transcript_path),
                execution_plan: Some(&execution_plan_path),
                reviewer_plan: Some(&reviewer_plan_path),
            },
            true,
        )?;
        validation_result?;
    }
    if !trusted_lifecycle(&run.artifact) {
        write_review_receipt_bundle(
            &receipt_bundle_path,
            &request,
            &run,
            ReviewReceiptPaths {
                artifact: &artifact_path,
                transcript: Some(&transcript_path),
                execution_plan: Some(&execution_plan_path),
                reviewer_plan: Some(&reviewer_plan_path),
            },
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
            ReviewReceiptPaths {
                artifact: &artifact_path,
                transcript: Some(&transcript_path),
                execution_plan: Some(&execution_plan_path),
                reviewer_plan: Some(&reviewer_plan_path),
            },
            false,
        )?;
        let result = github.apply_plan(&post_plan)?;
        write_json(&post_result_path, &result)?;
    } else {
        write_review_receipt_bundle(
            &receipt_bundle_path,
            &request,
            &run,
            ReviewReceiptPaths {
                artifact: &artifact_path,
                transcript: Some(&transcript_path),
                execution_plan: Some(&execution_plan_path),
                reviewer_plan: Some(&reviewer_plan_path),
            },
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

struct ReviewReceiptPaths<'a> {
    artifact: &'a Path,
    transcript: Option<&'a Path>,
    execution_plan: Option<&'a Path>,
    reviewer_plan: Option<&'a Path>,
}

fn write_review_receipt_bundle(
    path: &Path,
    request: &ReviewRequest,
    run: &ReviewRun,
    paths: ReviewReceiptPaths<'_>,
    validation_failed: bool,
) -> Result<cerberus::ReviewReceiptBundle> {
    let bundle = build_review_receipt_bundle(ReceiptBundleInput {
        request,
        artifact: &run.artifact,
        harness: &run.execution_plan.harness,
        telemetry: &run.telemetry,
        transcript: &run.transcript,
        artifact_uri: paths.artifact.display().to_string(),
        transcript_uri: paths.transcript.map(|path| path.display().to_string()),
        execution_plan_uri: paths.execution_plan.map(|path| path.display().to_string()),
        reviewer_plan_uri: paths.reviewer_plan.map(|path| path.display().to_string()),
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

fn reviewer_plan_path_for(out: &Path) -> PathBuf {
    let file_name = out
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("artifact.json");
    let reviewer_plan_name = if file_name == "artifact.json" {
        "reviewer_plan.json".to_string()
    } else if let Some(prefix) = file_name.strip_suffix("-artifact.json") {
        format!("{prefix}-reviewer_plan.json")
    } else if let Some(prefix) = file_name.strip_suffix(".json") {
        format!("{prefix}-reviewer_plan.json")
    } else {
        format!("{file_name}-reviewer_plan.json")
    };
    sibling_path(out, &reviewer_plan_name)
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

    fn default_scoped_key_args() -> ScopedKeyArgs {
        ScopedKeyArgs {
            openrouter_scoped_key: false,
            openrouter_provisioning_key_file: None,
            openrouter_provisioning_key_env: None,
            openrouter_key_limit_usd: 5.0,
            openrouter_orphan_sweep_seconds: 1800,
        }
    }

    #[test]
    fn scoped_key_client_is_none_when_flag_is_off() {
        let client = resolve_scoped_key_client(&default_scoped_key_args()).expect("resolves");
        assert!(
            client.is_none(),
            "no provisioning key should be required unless --openrouter-scoped-key is set"
        );
    }

    #[test]
    fn mint_scoped_openrouter_key_is_a_noop_without_a_client() {
        let request_path =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("fixtures/requests/diff-only.json");
        let mut request: ReviewRequest = read_json(&request_path).expect("fixture request loads");
        let allowed_env_before = request.policy.allowed_env.clone();

        let guard = mint_scoped_openrouter_key(None, &mut request, &default_scoped_key_args())
            .expect("no client means no minting");

        assert!(guard.is_none());
        assert_eq!(
            request.policy.allowed_env, allowed_env_before,
            "request must be untouched when scoped-key minting was not requested"
        );
    }

    #[test]
    fn provisioning_key_resolves_from_file() {
        let dir = tempfile::tempdir().expect("tempdir");
        let path = dir.path().join("provisioning-key.txt");
        fs::write(&path, "mgmt-key-from-file\n").expect("write key file");

        let key = resolve_openrouter_provisioning_key(Some(&path), None).expect("reads file");
        assert_eq!(key, "mgmt-key-from-file");
    }

    #[test]
    fn provisioning_key_resolves_from_explicit_env_var() {
        let var = "CERBERUS_TEST_OPENROUTER_PROVISIONING_KEY";
        std::env::set_var(var, "mgmt-key-from-env");
        let key = resolve_openrouter_provisioning_key(None, Some(var)).expect("reads env var");
        std::env::remove_var(var);
        assert_eq!(key, "mgmt-key-from-env");
    }

    #[test]
    fn provisioning_key_rejects_both_sources_at_once() {
        let dir = tempfile::tempdir().expect("tempdir");
        let path = dir.path().join("provisioning-key.txt");
        fs::write(&path, "irrelevant").expect("write key file");

        let err = resolve_openrouter_provisioning_key(Some(&path), Some("SOME_VAR")).unwrap_err();
        assert!(err.to_string().contains("exactly one explicit"));
    }

    #[test]
    fn provisioning_key_refuses_ambient_fallback() {
        let err = resolve_openrouter_provisioning_key(None, None).unwrap_err();
        assert!(
            err.to_string()
                .contains("requires an explicit provisioning key"),
            "must not silently fall back to ambient env: {err}"
        );
    }
}
