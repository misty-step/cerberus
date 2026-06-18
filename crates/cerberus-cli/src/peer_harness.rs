use anyhow::{bail, Context, Result};
use cerberus_adapter::CommandHarnessInput;
use cerberus_core::validate_reviewer_artifact_for_request;
use cerberus_schema::{
    Coverage, PeerHarnessCommandProfile, PeerHarnessCommandProfiles, ReviewerArtifact,
    ReviewerStatus, TokenUsage, Verdict, REVIEWER_ARTIFACT_VERSION,
};
use std::{
    env, fs,
    path::{Path, PathBuf},
};

const PROFILES_ENV: &str = "CERBERUS_PEER_HARNESS_PROFILES";
const LIVE_ENV: &str = "CERBERUS_PEER_HARNESS_LIVE";
const DEFAULT_PROFILES_PATH: &str = "fixtures/harnesses/peer-command-profiles.json";
const ARTIFACT_BEGIN_MARKER: &str = "CERBERUS_REVIEWER_ARTIFACT_JSON_BEGIN";
const ARTIFACT_END_MARKER: &str = "CERBERUS_REVIEWER_ARTIFACT_JSON_END";

fn main() -> Result<()> {
    run(env::args().skip(1), live_mode_requested())
}

fn run(args: impl IntoIterator<Item = String>, live_mode: bool) -> Result<()> {
    let args = args.into_iter().collect::<Vec<_>>();
    if args.iter().any(|arg| arg == "--help" || arg == "-h") {
        println!("{}", usage());
        return Ok(());
    }

    let args = RunnerArgs::parse(&args)?;
    if live_mode {
        bail!(
            "live peer harness execution is not implemented; unset {LIVE_ENV} and use the offline protocol runner"
        );
    }

    let profiles_path = profile_path(args.profiles_path);
    let profiles = read_profiles(&profiles_path)?;
    let profile = select_profile(&profiles, &args.harness_id)?;
    let input = read_input(&args.input_path)?;

    if let Some(path) = args.prompt_output_path.as_ref() {
        write_prompt(path, &render_prompt(profile, &input))?;
    }

    let artifact = match args.transcript_path.as_ref() {
        Some(path) => read_transcript_artifact(path)?,
        None => offline_artifact(profile, &input),
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
}

impl RunnerArgs {
    fn parse(args: &[String]) -> Result<Self> {
        let mut harness_id = None;
        let mut input_path = None;
        let mut output_path = None;
        let mut profiles_path = None;
        let mut prompt_output_path = None;
        let mut transcript_path = None;
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
        })
    }
}

fn usage() -> &'static str {
    "usage: cerberus-peer-harness --harness <id> --input <CommandHarnessInput.json> --output <ReviewerArtifact.v1.json> [--profiles <PeerHarnessCommandProfiles.v1.json>] [--prompt-output <path>] [--transcript <path>]"
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
        collections::BTreeMap,
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
            ],
            true,
        )
        .expect_err("live mode is fail closed");

        assert!(error
            .to_string()
            .contains("live peer harness execution is not implemented"));
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
