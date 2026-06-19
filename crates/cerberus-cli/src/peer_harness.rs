use anyhow::{bail, Context, Result};
use cerberus_adapter::{BoundedCommand, CommandHarnessInput};
use cerberus_core::validate_reviewer_artifact_for_request;
use cerberus_schema::{
    Coverage, PeerHarnessCommandProfile, PeerHarnessCommandProfiles, PeerHarnessExecutionPlan,
    PeerHarnessPromptMode, PeerHarnessTranscriptMarkers, ReviewerArtifact, ReviewerStatus,
    TokenUsage, Verdict, PEER_HARNESS_EXECUTION_PLAN_VERSION, REVIEWER_ARTIFACT_VERSION,
};
use std::{
    env, fs,
    path::{Path, PathBuf},
    time::Duration,
};

const PROFILES_ENV: &str = "CERBERUS_PEER_HARNESS_PROFILES";
const LIVE_ENV: &str = "CERBERUS_PEER_HARNESS_LIVE";
const PROVIDER_BUDGET_ACK_ENV: &str = "CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK";
const DEFAULT_PROFILES_PATH: &str = "fixtures/harnesses/peer-command-profiles.json";
const ARTIFACT_BEGIN_MARKER: &str = "CERBERUS_REVIEWER_ARTIFACT_JSON_BEGIN";
const ARTIFACT_END_MARKER: &str = "CERBERUS_REVIEWER_ARTIFACT_JSON_END";

fn main() -> Result<()> {
    run(env::args().skip(1), live_mode_requested())
}

fn run(args: impl IntoIterator<Item = String>, live_mode: bool) -> Result<()> {
    run_inner(args, live_mode, provider_budget_acknowledged())
}

fn run_inner(
    args: impl IntoIterator<Item = String>,
    live_mode: bool,
    provider_budget_acknowledged: bool,
) -> Result<()> {
    let args = args.into_iter().collect::<Vec<_>>();
    if args.iter().any(|arg| arg == "--help" || arg == "-h") {
        println!("{}", usage());
        return Ok(());
    }

    let args = RunnerArgs::parse(&args)?;
    let profiles_path = profile_path(args.profiles_path);
    let profiles = read_profiles(&profiles_path)?;
    let profile = select_profile(&profiles, &args.harness_id)?;
    let input = read_input(&args.input_path)?;
    let prompt = if live_mode || args.prompt_output_path.is_some() {
        Some(render_prompt(profile, &input))
    } else {
        None
    };

    if let Some(path) = args.execution_plan_output_path.as_ref() {
        write_execution_plan(
            path,
            &execution_plan(profile, &input, live_mode, provider_budget_acknowledged),
        )?;
    }

    if !live_mode && args.transcript_output_path.is_some() {
        bail!("--transcript-output requires {LIVE_ENV}=1");
    }

    if let Some(path) = args.prompt_output_path.as_ref() {
        write_prompt(path, prompt.as_deref().expect("prompt is rendered"))?;
    }

    let artifact = if live_mode {
        if args.transcript_path.is_some() {
            bail!(
                "--transcript is an offline fixture input and cannot be combined with {LIVE_ENV}=1"
            );
        }
        live_peer_artifact(
            profile,
            &input,
            prompt.as_deref().expect("prompt is rendered"),
            args.transcript_output_path.as_deref(),
            provider_budget_acknowledged,
        )?
    } else {
        match args.transcript_path.as_ref() {
            Some(path) => read_transcript_artifact(path)?,
            None => offline_artifact(profile, &input),
        }
    };
    let artifact =
        validate_reviewer_artifact_for_request(&input.reviewer, &input.request, artifact)
            .context("peer harness artifact failed request acceptance")?;
    write_artifact(&args.output_path, &artifact)?;
    Ok(())
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct RunnerArgs {
    harness_id: String,
    input_path: PathBuf,
    output_path: PathBuf,
    profiles_path: Option<PathBuf>,
    prompt_output_path: Option<PathBuf>,
    transcript_path: Option<PathBuf>,
    transcript_output_path: Option<PathBuf>,
    execution_plan_output_path: Option<PathBuf>,
}

impl RunnerArgs {
    fn parse(args: &[String]) -> Result<Self> {
        let mut harness_id = None;
        let mut input_path = None;
        let mut output_path = None;
        let mut profiles_path = None;
        let mut prompt_output_path = None;
        let mut transcript_path = None;
        let mut transcript_output_path = None;
        let mut execution_plan_output_path = None;
        let mut index = 0;

        while index < args.len() {
            match args[index].as_str() {
                "--harness" => {
                    harness_id = Some(required_value(args, index, "--harness")?);
                    index += 2;
                }
                "--input" => {
                    input_path = Some(PathBuf::from(required_value(args, index, "--input")?));
                    index += 2;
                }
                "--output" => {
                    output_path = Some(PathBuf::from(required_value(args, index, "--output")?));
                    index += 2;
                }
                "--profiles" => {
                    profiles_path = Some(PathBuf::from(required_value(args, index, "--profiles")?));
                    index += 2;
                }
                "--prompt-output" => {
                    prompt_output_path = Some(PathBuf::from(required_value(
                        args,
                        index,
                        "--prompt-output",
                    )?));
                    index += 2;
                }
                "--transcript" => {
                    transcript_path =
                        Some(PathBuf::from(required_value(args, index, "--transcript")?));
                    index += 2;
                }
                "--transcript-output" => {
                    transcript_output_path = Some(PathBuf::from(required_value(
                        args,
                        index,
                        "--transcript-output",
                    )?));
                    index += 2;
                }
                "--execution-plan-output" => {
                    execution_plan_output_path = Some(PathBuf::from(required_value(
                        args,
                        index,
                        "--execution-plan-output",
                    )?));
                    index += 2;
                }
                other => bail!("unknown peer harness argument {other:?}"),
            }
        }

        Ok(Self {
            harness_id: harness_id.context("cerberus-peer-harness requires --harness <id>")?,
            input_path: input_path.context("cerberus-peer-harness requires --input <path>")?,
            output_path: output_path.context("cerberus-peer-harness requires --output <path>")?,
            profiles_path,
            prompt_output_path,
            transcript_path,
            transcript_output_path,
            execution_plan_output_path,
        })
    }
}

fn usage() -> &'static str {
    "usage: cerberus-peer-harness --harness <id> --input <CommandHarnessInput.json> --output <ReviewerArtifact.v1.json> [--profiles <PeerHarnessCommandProfiles.v2.json>] [--prompt-output <path>] [--transcript <path>] [--transcript-output <path>] [--execution-plan-output <path>]"
}

fn required_value(args: &[String], index: usize, flag: &'static str) -> Result<String> {
    args.get(index + 1)
        .filter(|value| !value.starts_with("--"))
        .cloned()
        .with_context(|| format!("{flag} requires a value"))
}

fn live_mode_requested() -> bool {
    env::var(LIVE_ENV)
        .map(|value| matches!(value.as_str(), "1" | "true" | "TRUE" | "yes" | "YES"))
        .unwrap_or(false)
}

fn provider_budget_acknowledged() -> bool {
    env::var(PROVIDER_BUDGET_ACK_ENV)
        .map(|value| matches!(value.as_str(), "1" | "true" | "TRUE" | "yes" | "YES"))
        .unwrap_or(false)
}

fn profile_path(explicit: Option<PathBuf>) -> PathBuf {
    if let Some(path) = explicit {
        return path;
    }
    if let Some(path) = env::var_os(PROFILES_ENV) {
        return PathBuf::from(path);
    }

    let cwd_relative = PathBuf::from(DEFAULT_PROFILES_PATH);
    if cwd_relative.exists() {
        return cwd_relative;
    }

    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join(DEFAULT_PROFILES_PATH)
}

fn read_profiles(path: &Path) -> Result<PeerHarnessCommandProfiles> {
    let raw = fs::read_to_string(path)
        .with_context(|| format!("failed to read peer harness profiles {}", path.display()))?;
    let profiles: PeerHarnessCommandProfiles = serde_json::from_str(&raw)
        .with_context(|| format!("failed to parse peer harness profiles {}", path.display()))?;
    profiles
        .validate()
        .with_context(|| format!("invalid peer harness profiles {}", path.display()))?;
    Ok(profiles)
}

fn select_profile<'a>(
    profiles: &'a PeerHarnessCommandProfiles,
    harness_id: &str,
) -> Result<&'a PeerHarnessCommandProfile> {
    profiles
        .profiles
        .iter()
        .find(|profile| profile.harness_id == harness_id)
        .with_context(|| format!("peer harness profile {harness_id:?} was not found"))
}

fn read_input(path: &Path) -> Result<CommandHarnessInput> {
    let raw = fs::read_to_string(path)
        .with_context(|| format!("failed to read command harness input {}", path.display()))?;
    let input: CommandHarnessInput = serde_json::from_str(&raw)
        .with_context(|| format!("failed to parse command harness input {}", path.display()))?;
    input
        .request
        .validate()
        .context("command harness input request failed schema validation")?;
    Ok(input)
}

fn offline_artifact(
    profile: &PeerHarnessCommandProfile,
    input: &CommandHarnessInput,
) -> ReviewerArtifact {
    let files = input
        .request
        .change
        .files
        .iter()
        .map(|file| file.path.clone())
        .collect();
    let reason = format!(
        "Peer harness {:?} profile validated, but live {:?} execution is disabled in the offline protocol runner.",
        profile.harness_id, profile.peer.command
    );

    ReviewerArtifact {
        schema_version: REVIEWER_ARTIFACT_VERSION.to_string(),
        reviewer_id: input.reviewer.id.clone(),
        perspective: input.reviewer.perspective.clone(),
        model: input.reviewer.model.clone(),
        status: ReviewerStatus::Degraded,
        verdict: Verdict::Skip,
        summary: reason.clone(),
        findings: vec![],
        coverage: Coverage {
            files_reviewed: files,
            files_with_findings: vec![],
        },
        usage: TokenUsage {
            prompt_tokens: 0,
            completion_tokens: 0,
        },
        cost_usd: 0.0,
        degraded_reason: Some(reason),
    }
}

fn execution_plan(
    profile: &PeerHarnessCommandProfile,
    input: &CommandHarnessInput,
    live_mode: bool,
    provider_budget_acknowledged: bool,
) -> PeerHarnessExecutionPlan {
    let model = model_for_template(&profile.peer.args_template, &input.reviewer.model);
    let resolved_args = profile
        .peer
        .args_template
        .iter()
        .map(|arg| arg.replace("{model}", &model))
        .collect();
    let (env_available, env_missing) = profile
        .env_required
        .iter()
        .cloned()
        .partition(|name| env::var_os(name.as_str()).is_some());

    PeerHarnessExecutionPlan {
        schema_version: PEER_HARNESS_EXECUTION_PLAN_VERSION.to_string(),
        harness_id: profile.harness_id.clone(),
        peer_command: profile.peer.command.clone(),
        resolved_args,
        prompt_mode: profile.peer.prompt_mode,
        output_contract: profile.output_contract,
        timeout_ms: profile.timeout_ms,
        env_required: profile.env_required.clone(),
        requires_provider_budget_ack: profile.requires_provider_budget_ack,
        env_available,
        env_missing,
        provider_budget_acknowledged,
        live_mode_requested: live_mode,
        transcript_markers: PeerHarnessTranscriptMarkers {
            begin: ARTIFACT_BEGIN_MARKER.to_string(),
            end: ARTIFACT_END_MARKER.to_string(),
        },
        unsupported: profile.unsupported.clone(),
        notes: Some(
            "Exact peer command plan; rendered prompt text is intentionally represented by the {prompt} placeholder."
                .to_string(),
        ),
    }
}

fn model_for_template(args_template: &[String], reviewer_model: &str) -> String {
    if args_template
        .iter()
        .any(|arg| arg.contains("openrouter/{model}"))
    {
        return reviewer_model
            .strip_prefix("openrouter/")
            .unwrap_or(reviewer_model)
            .to_string();
    }
    reviewer_model.to_string()
}

fn live_peer_artifact(
    profile: &PeerHarnessCommandProfile,
    input: &CommandHarnessInput,
    prompt: &str,
    transcript_output_path: Option<&Path>,
    provider_budget_acknowledged: bool,
) -> Result<ReviewerArtifact> {
    ensure_provider_budget_ack(profile, provider_budget_acknowledged)?;
    ensure_live_prompt_transport(profile)?;
    ensure_required_env(profile)?;
    let output = live_peer_command(profile, input, prompt)
        .run()
        .context("live peer command failed")?;
    if let Some(path) = transcript_output_path {
        fs::write(path, &output.stdout)
            .with_context(|| format!("failed to write live peer transcript {}", path.display()))?;
    }
    parse_transcript_artifact(&output.stdout)
        .context("live peer transcript was not a valid artifact")
}

fn ensure_provider_budget_ack(
    profile: &PeerHarnessCommandProfile,
    provider_budget_acknowledged: bool,
) -> Result<()> {
    if profile.requires_provider_budget_ack && !provider_budget_acknowledged {
        bail!(
            "peer harness profile {:?} requires provider budget acknowledgement; set {PROVIDER_BUDGET_ACK_ENV}=1 to allow paid/provider-backed execution",
            profile.harness_id
        );
    }
    Ok(())
}

fn ensure_live_prompt_transport(profile: &PeerHarnessCommandProfile) -> Result<()> {
    if profile.requires_provider_budget_ack
        && matches!(
            profile.peer.prompt_mode,
            PeerHarnessPromptMode::ArgvMessage | PeerHarnessPromptMode::WrapperRenderedPrompt
        )
    {
        bail!(
            "peer harness profile {:?} uses argv prompt transport; provider-backed live execution requires stdin or a private prompt-file wrapper",
            profile.harness_id
        );
    }
    Ok(())
}

fn ensure_required_env(profile: &PeerHarnessCommandProfile) -> Result<()> {
    let missing = profile
        .env_required
        .iter()
        .filter(|name| env::var_os(name.as_str()).is_none())
        .cloned()
        .collect::<Vec<_>>();
    if !missing.is_empty() {
        bail!(
            "peer harness profile {:?} is missing required environment variable(s): {}",
            profile.harness_id,
            missing.join(", ")
        );
    }
    Ok(())
}

fn live_peer_command(
    profile: &PeerHarnessCommandProfile,
    input: &CommandHarnessInput,
    prompt: &str,
) -> BoundedCommand {
    let model = model_for_template(&profile.peer.args_template, &input.reviewer.model);
    let resolved_model_args = profile
        .peer
        .args_template
        .iter()
        .map(|arg| arg.replace("{model}", &model));
    let command = BoundedCommand::new(profile.peer.command.clone())
        .timeout(Duration::from_millis(profile.timeout_ms));

    match profile.peer.prompt_mode {
        PeerHarnessPromptMode::ArgvMessage | PeerHarnessPromptMode::WrapperRenderedPrompt => {
            command.args(resolved_model_args.map(|arg| arg.replace("{prompt}", prompt)))
        }
        PeerHarnessPromptMode::StdinText => command
            .args(resolved_model_args)
            .stdin_text(prompt.to_string()),
    }
}

fn render_prompt(profile: &PeerHarnessCommandProfile, input: &CommandHarnessInput) -> String {
    let files = input
        .request
        .change
        .files
        .iter()
        .map(|file| {
            format!(
                "- {} ({:?}, +{}, -{})",
                file.path, file.status, file.additions, file.deletions
            )
        })
        .collect::<Vec<_>>()
        .join("\n");
    let acceptance = if input.request.context.acceptance.is_empty() {
        "- none".to_string()
    } else {
        input
            .request
            .context
            .acceptance
            .iter()
            .map(|item| format!("- {item}"))
            .collect::<Vec<_>>()
            .join("\n")
    };
    let description = input
        .request
        .change
        .description
        .as_deref()
        .unwrap_or("none");

    format!(
        r#"You are a Cerberus peer reviewer. Return exactly one JSON object matching ReviewerArtifact.v1 between the required Cerberus artifact markers. Do not include markdown inside the markers.

Reviewer:
- id: {reviewer_id}
- perspective: {perspective}
- model: {model}

Peer harness:
- harness_id: {harness_id}
- peer_command: {peer_command}
- output_contract: reviewer_artifact_file

Request:
- request_id: {request_id}
- title: {title}
- description: {description}

Acceptance:
{acceptance}

Changed files:
{files}

Rules:
- reviewer_id, perspective, and model must match the reviewer above.
- coverage.files_reviewed must list exactly the changed files above.
- findings must cite only reviewed files.
- PASS artifacts must not contain findings.
- major or critical findings require FAIL.
- completed artifacts must not use SKIP.

Output format:
CERBERUS_REVIEWER_ARTIFACT_JSON_BEGIN
{{ ... ReviewerArtifact.v1 JSON ... }}
CERBERUS_REVIEWER_ARTIFACT_JSON_END

Diff:
```diff
{diff}
```
"#,
        reviewer_id = input.reviewer.id,
        perspective = input.reviewer.perspective,
        model = input.reviewer.model,
        harness_id = profile.harness_id,
        peer_command = profile.peer.command,
        request_id = input.request.request_id,
        title = input.request.change.title,
        description = description,
        acceptance = acceptance,
        files = files,
        diff = input.request.change.diff,
    )
}

fn write_prompt(path: &Path, prompt: &str) -> Result<()> {
    fs::write(path, prompt).with_context(|| format!("failed to write prompt {}", path.display()))
}

fn write_execution_plan(path: &Path, plan: &PeerHarnessExecutionPlan) -> Result<()> {
    plan.validate()
        .context("peer harness execution plan failed schema validation")?;
    let json = serde_json::to_string_pretty(plan)
        .context("failed to serialize peer harness execution plan")?;
    fs::write(path, format!("{json}\n")).with_context(|| {
        format!(
            "failed to write peer harness execution plan {}",
            path.display()
        )
    })
}

fn read_transcript_artifact(path: &Path) -> Result<ReviewerArtifact> {
    let raw = fs::read_to_string(path)
        .with_context(|| format!("failed to read peer harness transcript {}", path.display()))?;
    parse_transcript_artifact(&raw)
        .with_context(|| format!("failed to parse peer harness transcript {}", path.display()))
}

fn parse_transcript_artifact(transcript: &str) -> Result<ReviewerArtifact> {
    let begin_count = transcript.matches(ARTIFACT_BEGIN_MARKER).count();
    if begin_count != 1 {
        bail!(
            "transcript must contain exactly one {ARTIFACT_BEGIN_MARKER} marker, found {begin_count}"
        );
    }
    let end_count = transcript.matches(ARTIFACT_END_MARKER).count();
    if end_count != 1 {
        bail!(
            "transcript must contain exactly one {ARTIFACT_END_MARKER} marker, found {end_count}"
        );
    }

    let (_, after_begin) = transcript
        .split_once(ARTIFACT_BEGIN_MARKER)
        .context("transcript artifact begin marker was missing")?;
    let (json, _) = after_begin
        .split_once(ARTIFACT_END_MARKER)
        .context("transcript artifact end marker appeared before begin marker")?;
    let json = json.trim();
    if json.is_empty() {
        bail!("transcript artifact JSON block was empty");
    }

    serde_json::from_str(json).context("transcript artifact JSON was not ReviewerArtifact.v1")
}

fn write_artifact(path: &Path, artifact: &ReviewerArtifact) -> Result<()> {
    let json = serde_json::to_string_pretty(artifact)
        .context("failed to serialize peer harness artifact")?;
    fs::write(path, format!("{json}\n"))
        .with_context(|| format!("failed to write peer harness artifact {}", path.display()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use cerberus_core::{review_with_harness, HarnessRuntimeError, ReviewHarness};
    use cerberus_schema::{
        Change, ChangedFile, FileStatus, ReviewConfig, ReviewContext, ReviewRequest, ReviewSource,
        ReviewerConfig, REVIEW_CONFIG_VERSION, REVIEW_REQUEST_VERSION,
    };
    use std::{
        collections::{BTreeMap, BTreeSet},
        sync::atomic::{AtomicU64, Ordering},
    };

    static NEXT_TEMP_ID: AtomicU64 = AtomicU64::new(0);

    #[test]
    fn peer_harness_runner_writes_offline_artifact() {
        let paths = TestPaths::new();
        write_input(&paths.input);

        run(
            vec![
                "--harness".to_string(),
                "pi".to_string(),
                "--input".to_string(),
                paths.input.display().to_string(),
                "--output".to_string(),
                paths.output.display().to_string(),
                "--profiles".to_string(),
                profiles_path().display().to_string(),
            ],
            false,
        )
        .expect("offline runner writes artifact");

        let artifact = read_artifact(&paths.output);
        assert_eq!(artifact.reviewer_id, "peer-runner-reviewer");
        assert_eq!(artifact.perspective, "correctness");
        assert_eq!(artifact.model, "openrouter/test-model");
        assert_eq!(artifact.status, ReviewerStatus::Degraded);
        assert_eq!(artifact.verdict, Verdict::Skip);
        assert_eq!(artifact.coverage.files_reviewed, ["src/lib.rs"]);
        assert!(artifact.findings.is_empty());
        assert!(artifact
            .degraded_reason
            .as_deref()
            .is_some_and(|reason| reason.contains("live \"pi\" execution is disabled")));

        let config = ReviewConfig {
            schema_version: REVIEW_CONFIG_VERSION.to_string(),
            config_id: "peer-runner-test".to_string(),
            reviewers: vec![input().reviewer],
            confidence_min: 0.7,
        };
        let run = review_with_harness(&request(), &config, &StaticHarness(artifact))
            .expect("core accepts offline runner artifact");
        assert!(run.degraded);
        assert_eq!(run.verdict, Verdict::Skip);
    }

    #[test]
    fn peer_harness_runner_writes_execution_plan_without_live_provider_call() {
        let paths = TestPaths::new();
        write_input(&paths.input);

        run(
            vec![
                "--harness".to_string(),
                "pi".to_string(),
                "--input".to_string(),
                paths.input.display().to_string(),
                "--output".to_string(),
                paths.output.display().to_string(),
                "--profiles".to_string(),
                profiles_path().display().to_string(),
                "--execution-plan-output".to_string(),
                paths.plan.display().to_string(),
            ],
            false,
        )
        .expect("offline runner writes artifact and execution plan");

        let plan = read_execution_plan(&paths.plan);
        assert_eq!(plan.schema_version, PEER_HARNESS_EXECUTION_PLAN_VERSION);
        assert_eq!(plan.harness_id, "pi");
        assert_eq!(plan.peer_command, "pi");
        assert_eq!(plan.resolved_args[5], "openrouter/test-model");
        assert!(!plan
            .resolved_args
            .iter()
            .any(|arg| arg.contains("openrouter/openrouter")));
        assert_eq!(
            plan.resolved_args
                .iter()
                .filter(|arg| arg.contains("{prompt}"))
                .count(),
            1
        );
        assert!(!plan
            .resolved_args
            .iter()
            .any(|arg| arg.contains("diff --git")));
        assert_eq!(plan.env_required, vec!["OPENROUTER_API_KEY".to_string()]);
        assert!(plan.requires_provider_budget_ack);
        assert_eq!(
            plan.provider_budget_acknowledged,
            provider_budget_acknowledged()
        );
        assert_eq!(resolved_env_names(&plan), required_env_names(&plan));
        assert!(!plan.live_mode_requested);

        let artifact = read_artifact(&paths.output);
        assert_eq!(artifact.status, ReviewerStatus::Degraded);
    }

    #[test]
    fn peer_harness_runner_writes_execution_plan_before_refusing_provider_profile_live_mode() {
        let paths = TestPaths::new();
        write_input(&paths.input);

        let error = run_inner(
            vec![
                "--harness".to_string(),
                "pi".to_string(),
                "--input".to_string(),
                paths.input.display().to_string(),
                "--output".to_string(),
                paths.output.display().to_string(),
                "--profiles".to_string(),
                profiles_path().display().to_string(),
                "--execution-plan-output".to_string(),
                paths.plan.display().to_string(),
            ],
            true,
            false,
        )
        .expect_err("provider profile live mode requires budget acknowledgement");

        assert!(error.to_string().contains("requires provider budget"));
        let plan = read_execution_plan(&paths.plan);
        assert!(plan.live_mode_requested);
        assert!(plan.requires_provider_budget_ack);
        assert!(!plan.provider_budget_acknowledged);
        assert!(!paths.output.exists());
    }

    #[test]
    fn peer_harness_live_invokes_fixture_peer_and_writes_transcript() {
        let paths = TestPaths::new();
        write_input(&paths.input);
        write_live_profile(
            &paths.profiles,
            "fixture-live",
            "argv-success",
            PeerHarnessPromptMode::ArgvMessage,
            2_000,
            false,
        );

        run_inner(
            vec![
                "--harness".to_string(),
                "fixture-live".to_string(),
                "--input".to_string(),
                paths.input.display().to_string(),
                "--output".to_string(),
                paths.output.display().to_string(),
                "--profiles".to_string(),
                paths.profiles.display().to_string(),
                "--transcript-output".to_string(),
                paths.transcript.display().to_string(),
            ],
            true,
            false,
        )
        .expect("fixture live peer writes artifact");

        let artifact = read_artifact(&paths.output);
        assert_eq!(artifact.status, ReviewerStatus::Completed);
        assert_eq!(artifact.verdict, Verdict::Pass);
        assert_eq!(artifact.coverage.files_reviewed, ["src/lib.rs"]);
        let transcript = fs::read_to_string(&paths.transcript).expect("transcript is written");
        assert!(transcript.contains(ARTIFACT_BEGIN_MARKER));
        assert!(transcript.contains(ARTIFACT_END_MARKER));
    }

    #[test]
    fn peer_harness_live_supports_stdin_prompt_mode() {
        let paths = TestPaths::new();
        write_input(&paths.input);
        write_live_profile(
            &paths.profiles,
            "fixture-live-stdin",
            "stdin-success",
            PeerHarnessPromptMode::StdinText,
            2_000,
            false,
        );

        run_inner(
            vec![
                "--harness".to_string(),
                "fixture-live-stdin".to_string(),
                "--input".to_string(),
                paths.input.display().to_string(),
                "--output".to_string(),
                paths.output.display().to_string(),
                "--profiles".to_string(),
                paths.profiles.display().to_string(),
            ],
            true,
            false,
        )
        .expect("stdin live peer writes artifact");

        let artifact = read_artifact(&paths.output);
        assert_eq!(artifact.status, ReviewerStatus::Completed);
        assert_eq!(artifact.verdict, Verdict::Pass);
    }

    #[test]
    fn peer_harness_live_rejects_malformed_peer_transcript() {
        let paths = TestPaths::new();
        write_input(&paths.input);
        write_live_profile(
            &paths.profiles,
            "fixture-live-malformed",
            "malformed",
            PeerHarnessPromptMode::ArgvMessage,
            2_000,
            false,
        );

        let error = run_inner(
            vec![
                "--harness".to_string(),
                "fixture-live-malformed".to_string(),
                "--input".to_string(),
                paths.input.display().to_string(),
                "--output".to_string(),
                paths.output.display().to_string(),
                "--profiles".to_string(),
                paths.profiles.display().to_string(),
                "--transcript-output".to_string(),
                paths.transcript.display().to_string(),
            ],
            true,
            false,
        )
        .expect_err("malformed live transcript rejects");

        assert!(error_chain_contains(&error, "exactly one"));
        assert!(paths.transcript.exists());
        assert!(!paths.output.exists());
    }

    #[test]
    fn peer_harness_live_times_out_without_artifact() {
        let paths = TestPaths::new();
        write_input(&paths.input);
        write_live_profile(
            &paths.profiles,
            "fixture-live-sleep",
            "sleep",
            PeerHarnessPromptMode::ArgvMessage,
            20,
            false,
        );

        let error = run_inner(
            vec![
                "--harness".to_string(),
                "fixture-live-sleep".to_string(),
                "--input".to_string(),
                paths.input.display().to_string(),
                "--output".to_string(),
                paths.output.display().to_string(),
                "--profiles".to_string(),
                paths.profiles.display().to_string(),
            ],
            true,
            false,
        )
        .expect_err("live peer timeout rejects");

        assert!(error_chain_contains(&error, "exceeded"));
        assert!(!paths.output.exists());
    }

    #[test]
    fn peer_harness_live_requires_budget_ack_before_provider_profile_execution() {
        let paths = TestPaths::new();
        write_input(&paths.input);
        write_live_profile(
            &paths.profiles,
            "fixture-live-provider",
            "argv-success",
            PeerHarnessPromptMode::ArgvMessage,
            2_000,
            true,
        );

        let error = run_inner(
            vec![
                "--harness".to_string(),
                "fixture-live-provider".to_string(),
                "--input".to_string(),
                paths.input.display().to_string(),
                "--output".to_string(),
                paths.output.display().to_string(),
                "--profiles".to_string(),
                paths.profiles.display().to_string(),
            ],
            true,
            false,
        )
        .expect_err("budget acknowledgement is required");

        assert!(error.to_string().contains("requires provider budget"));
        assert!(!paths.output.exists());
    }

    #[test]
    fn peer_harness_live_rejects_provider_argv_prompt_transport_even_with_budget_ack() {
        let paths = TestPaths::new();
        write_input(&paths.input);
        write_live_profile(
            &paths.profiles,
            "fixture-live-provider",
            "argv-success",
            PeerHarnessPromptMode::ArgvMessage,
            2_000,
            true,
        );

        let error = run_inner(
            vec![
                "--harness".to_string(),
                "fixture-live-provider".to_string(),
                "--input".to_string(),
                paths.input.display().to_string(),
                "--output".to_string(),
                paths.output.display().to_string(),
                "--profiles".to_string(),
                paths.profiles.display().to_string(),
            ],
            true,
            true,
        )
        .expect_err("provider-backed argv prompt transport is refused");

        assert!(error.to_string().contains("argv prompt transport"));
        assert!(!paths.output.exists());
    }

    #[test]
    fn peer_harness_runner_writes_prompt_and_parses_transcript_artifact() {
        let paths = TestPaths::new();
        write_input(&paths.input);

        run(
            vec![
                "--harness".to_string(),
                "pi".to_string(),
                "--input".to_string(),
                paths.input.display().to_string(),
                "--output".to_string(),
                paths.output.display().to_string(),
                "--profiles".to_string(),
                profiles_path().display().to_string(),
                "--prompt-output".to_string(),
                paths.prompt.display().to_string(),
                "--transcript".to_string(),
                transcript_path().display().to_string(),
            ],
            false,
        )
        .expect("transcript fixture is parsed");

        let prompt = fs::read_to_string(&paths.prompt).expect("prompt is written");
        assert!(prompt.contains("ReviewerArtifact.v1"));
        assert!(prompt.contains("peer-runner-reviewer"));
        assert!(prompt.contains("diff --git a/src/lib.rs b/src/lib.rs"));

        let artifact = read_artifact(&paths.output);
        assert_eq!(artifact.status, ReviewerStatus::Completed);
        assert_eq!(artifact.verdict, Verdict::Warn);
        assert_eq!(artifact.findings.len(), 1);
        assert_eq!(
            artifact.findings[0].id,
            "peer-runner-reviewer-src-lib-rs-missing-assertion"
        );

        let config = ReviewConfig {
            schema_version: REVIEW_CONFIG_VERSION.to_string(),
            config_id: "peer-runner-transcript-test".to_string(),
            reviewers: vec![input().reviewer],
            confidence_min: 0.7,
        };
        let run = review_with_harness(&request(), &config, &StaticHarness(artifact))
            .expect("core accepts parsed transcript artifact");
        assert!(!run.degraded);
        assert_eq!(run.verdict, Verdict::Warn);
    }

    #[test]
    fn peer_harness_runner_rejects_completed_skip_transcript_artifact() {
        let paths = TestPaths::new();
        write_input(&paths.input);
        let transcript = paths.root().join("completed-skip.txt");
        fs::write(
            &transcript,
            format!(
                "{ARTIFACT_BEGIN_MARKER}\n{}\n{ARTIFACT_END_MARKER}\n",
                serde_json::to_string_pretty(&ReviewerArtifact {
                    schema_version: REVIEWER_ARTIFACT_VERSION.to_string(),
                    reviewer_id: "peer-runner-reviewer".to_string(),
                    perspective: "correctness".to_string(),
                    model: "openrouter/test-model".to_string(),
                    status: ReviewerStatus::Completed,
                    verdict: Verdict::Skip,
                    summary: "completed skip should reject".to_string(),
                    findings: vec![],
                    coverage: Coverage {
                        files_reviewed: vec!["src/lib.rs".to_string()],
                        files_with_findings: vec![],
                    },
                    usage: TokenUsage {
                        prompt_tokens: 1,
                        completion_tokens: 1,
                    },
                    cost_usd: 0.0,
                    degraded_reason: None,
                })
                .expect("artifact serializes")
            ),
        )
        .expect("transcript fixture is written");

        let error = run(
            vec![
                "--harness".to_string(),
                "pi".to_string(),
                "--input".to_string(),
                paths.input.display().to_string(),
                "--output".to_string(),
                paths.output.display().to_string(),
                "--profiles".to_string(),
                profiles_path().display().to_string(),
                "--transcript".to_string(),
                transcript.display().to_string(),
            ],
            false,
        )
        .expect_err("completed SKIP transcript is rejected");

        assert!(error_chain_contains(
            &error,
            "completed artifact cannot have SKIP verdict"
        ));
        assert!(!paths.output.exists());
    }

    #[test]
    fn peer_harness_runner_uses_default_profile_fixture() {
        let paths = TestPaths::new();
        write_input(&paths.input);

        run(
            vec![
                "--harness".to_string(),
                "goose".to_string(),
                "--input".to_string(),
                paths.input.display().to_string(),
                "--output".to_string(),
                paths.output.display().to_string(),
            ],
            false,
        )
        .expect("default profile path resolves in repo checkout");

        let artifact = read_artifact(&paths.output);
        assert!(artifact
            .degraded_reason
            .as_deref()
            .is_some_and(|reason| reason.contains("live \"goose\" execution is disabled")));
    }

    #[test]
    fn peer_harness_runner_rejects_unknown_harness() {
        let paths = TestPaths::new();
        write_input(&paths.input);

        let error = run(
            vec![
                "--harness".to_string(),
                "missing".to_string(),
                "--input".to_string(),
                paths.input.display().to_string(),
                "--output".to_string(),
                paths.output.display().to_string(),
                "--profiles".to_string(),
                profiles_path().display().to_string(),
            ],
            false,
        )
        .expect_err("unknown harness fails");

        assert!(error
            .to_string()
            .contains("peer harness profile \"missing\" was not found"));
        assert!(!paths.output.exists());
    }

    #[test]
    fn peer_harness_runner_refuses_live_mode() {
        let paths = TestPaths::new();
        write_input(&paths.input);

        let error = run_inner(
            vec![
                "--harness".to_string(),
                "pi".to_string(),
                "--input".to_string(),
                paths.input.display().to_string(),
                "--output".to_string(),
                paths.output.display().to_string(),
                "--profiles".to_string(),
                profiles_path().display().to_string(),
            ],
            true,
            false,
        )
        .expect_err("provider profile live mode is budget gated");

        assert!(error.to_string().contains("requires provider budget"));
        assert!(!paths.output.exists());
    }

    #[test]
    fn peer_harness_runner_rejects_transcript_without_exact_artifact_block() {
        let error = parse_transcript_artifact("no artifact here")
            .expect_err("missing markers reject transcript");
        assert!(error
            .to_string()
            .contains("exactly one CERBERUS_REVIEWER_ARTIFACT_JSON_BEGIN"));

        let error = parse_transcript_artifact(
            "CERBERUS_REVIEWER_ARTIFACT_JSON_BEGIN\n{}\nCERBERUS_REVIEWER_ARTIFACT_JSON_END\nCERBERUS_REVIEWER_ARTIFACT_JSON_END",
        )
        .expect_err("duplicate end marker rejects transcript");
        assert!(error
            .to_string()
            .contains("exactly one CERBERUS_REVIEWER_ARTIFACT_JSON_END"));
    }

    #[test]
    fn peer_harness_runner_requires_input_output_and_harness() {
        let error = run(vec![], false).expect_err("missing args fail");
        assert!(error
            .to_string()
            .contains("cerberus-peer-harness requires --harness"));

        let error = run(vec!["--harness".to_string(), "pi".to_string()], false)
            .expect_err("missing input fails");
        assert!(error
            .to_string()
            .contains("cerberus-peer-harness requires --input"));

        let error = run(
            vec![
                "--harness".to_string(),
                "pi".to_string(),
                "--input".to_string(),
                "input.json".to_string(),
            ],
            false,
        )
        .expect_err("missing output fails");
        assert!(error
            .to_string()
            .contains("cerberus-peer-harness requires --output"));
    }

    struct StaticHarness(ReviewerArtifact);

    impl ReviewHarness for StaticHarness {
        fn review(
            &self,
            _reviewer: &ReviewerConfig,
            _request: &ReviewRequest,
        ) -> Result<ReviewerArtifact, HarnessRuntimeError> {
            Ok(self.0.clone())
        }
    }

    struct TestPaths {
        input: PathBuf,
        output: PathBuf,
        prompt: PathBuf,
        plan: PathBuf,
        transcript: PathBuf,
        profiles: PathBuf,
    }

    impl TestPaths {
        fn new() -> Self {
            let suffix = NEXT_TEMP_ID.fetch_add(1, Ordering::Relaxed);
            let root = env::temp_dir().join(format!(
                "cerberus-peer-harness-runner-{}-{suffix}",
                std::process::id()
            ));
            fs::create_dir(&root).expect("test temp dir is created");
            Self {
                input: root.join("input.json"),
                output: root.join("output.json"),
                prompt: root.join("prompt.txt"),
                plan: root.join("execution-plan.json"),
                transcript: root.join("transcript.txt"),
                profiles: root.join("profiles.json"),
            }
        }

        fn root(&self) -> &Path {
            self.input.parent().expect("test path has parent")
        }
    }

    impl Drop for TestPaths {
        fn drop(&mut self) {
            if let Some(root) = self.input.parent() {
                let _ = fs::remove_dir_all(root);
            }
        }
    }

    fn profiles_path() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .join(DEFAULT_PROFILES_PATH)
    }

    fn transcript_path() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .join("fixtures/harnesses/peer-transcript-with-finding.txt")
    }

    fn write_input(path: &Path) {
        let json = serde_json::to_string_pretty(&input()).expect("input serializes");
        fs::write(path, format!("{json}\n")).expect("input fixture is written");
    }

    fn read_artifact(path: &Path) -> ReviewerArtifact {
        let artifact: ReviewerArtifact =
            serde_json::from_str(&fs::read_to_string(path).expect("artifact file is readable"))
                .expect("artifact parses");
        artifact.validate().expect("artifact validates");
        artifact
    }

    fn read_execution_plan(path: &Path) -> PeerHarnessExecutionPlan {
        let plan: PeerHarnessExecutionPlan =
            serde_json::from_str(&fs::read_to_string(path).expect("plan file is readable"))
                .expect("plan parses");
        plan.validate().expect("plan validates");
        plan
    }

    fn write_live_profile(
        path: &Path,
        harness_id: &str,
        mode: &str,
        prompt_mode: PeerHarnessPromptMode,
        timeout_ms: u64,
        requires_provider_budget_ack: bool,
    ) {
        let args_template = match prompt_mode {
            PeerHarnessPromptMode::ArgvMessage | PeerHarnessPromptMode::WrapperRenderedPrompt => {
                vec![
                    fixture_live_script().display().to_string(),
                    mode.to_string(),
                    "{prompt}".to_string(),
                ]
            }
            PeerHarnessPromptMode::StdinText => {
                vec![
                    fixture_live_script().display().to_string(),
                    mode.to_string(),
                ]
            }
        };
        let profiles = PeerHarnessCommandProfiles {
            schema_version: cerberus_schema::PEER_HARNESS_COMMAND_PROFILES_VERSION.to_string(),
            observed_at: "2026-06-18".to_string(),
            profiles: vec![PeerHarnessCommandProfile {
                harness_id: harness_id.to_string(),
                command: "cerberus-peer-harness".to_string(),
                args: vec!["--harness".to_string(), harness_id.to_string()],
                timeout_ms,
                env_required: vec![],
                requires_provider_budget_ack,
                output_contract: cerberus_schema::PeerHarnessOutputContract::ReviewerArtifactFile,
                peer: cerberus_schema::PeerHarnessInvocation {
                    command: "sh".to_string(),
                    args_template,
                    prompt_mode,
                    notes: None,
                },
                unsupported: vec!["provider-backed execution".to_string()],
                notes: None,
            }],
        };
        profiles.validate().expect("live profile validates");
        let json = serde_json::to_string_pretty(&profiles).expect("profiles serialize");
        fs::write(path, format!("{json}\n")).expect("profiles fixture is written");
    }

    fn fixture_live_script() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .join("fixtures/harnesses/live-peer-reviewer.sh")
    }

    fn required_env_names(plan: &PeerHarnessExecutionPlan) -> BTreeSet<String> {
        plan.env_required.iter().cloned().collect()
    }

    fn resolved_env_names(plan: &PeerHarnessExecutionPlan) -> BTreeSet<String> {
        plan.env_available
            .iter()
            .chain(plan.env_missing.iter())
            .cloned()
            .collect()
    }

    fn error_chain_contains(error: &anyhow::Error, needle: &str) -> bool {
        error
            .chain()
            .any(|cause| cause.to_string().contains(needle))
    }

    fn input() -> CommandHarnessInput {
        CommandHarnessInput {
            reviewer: ReviewerConfig {
                id: "peer-runner-reviewer".to_string(),
                perspective: "correctness".to_string(),
                model: "openrouter/test-model".to_string(),
                fake_behavior: Default::default(),
            },
            request: request(),
        }
    }

    fn request() -> ReviewRequest {
        ReviewRequest {
            schema_version: REVIEW_REQUEST_VERSION.to_string(),
            request_id: "peer-runner-request".to_string(),
            source: ReviewSource::Fixture {
                name: "peer-runner".to_string(),
            },
            change: Change {
                title: "Peer runner fixture".to_string(),
                description: None,
                base_ref: None,
                head_ref: None,
                head_sha: Some("peer-runner-sha".to_string()),
                diff: "diff --git a/src/lib.rs b/src/lib.rs\n+peer harness runner\n".to_string(),
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
