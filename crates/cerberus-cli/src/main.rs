use anyhow::{bail, Context, Result};
use cerberus_adapter::{
    github_action_review_decision_from_event, github_action_skip_decision_from_event,
    run_hosted_api_dispatch_fixture, GithubActionReviewDecision, HostedApiDispatchTranscript,
};
use cerberus_core::{
    default_config, render_inline_comment_candidates, render_markdown, review,
    reviewer_config_candidate_from_eval_report, reviewer_config_import_dry_run,
    reviewer_config_promotion_fixture_request, validate_reviewer_config_packet, HarnessProbe,
};
use cerberus_schema::{
    EvalTaskSuite, HarnessModelEvaluationReport, HarnessModelMatrix, HarnessProfile,
    InlineCommentCandidate, LegacySurfaceInventory, ModelCandidate, PeerHarnessCommandProfiles,
    PeerHarnessExecutionPlan, ReviewConfig, ReviewRequest, ReviewRunArtifact, ReviewerArtifact,
    ReviewerConfigImportReport, ReviewerConfigPacket, StaleModelFinding, EVAL_TASK_SUITE_VERSION,
    HARNESS_MODEL_EVALUATION_REPORT_VERSION, HARNESS_MODEL_MATRIX_VERSION, HARNESS_PROFILE_VERSION,
    INLINE_COMMENT_CANDIDATE_VERSION, LEGACY_SURFACE_INVENTORY_VERSION, MODEL_CANDIDATE_VERSION,
    PEER_HARNESS_COMMAND_PROFILES_VERSION, PEER_HARNESS_EXECUTION_PLAN_VERSION,
    REVIEWER_ARTIFACT_VERSION, REVIEWER_CONFIG_IMPORT_REPORT_VERSION,
    REVIEWER_CONFIG_PACKET_VERSION, REVIEW_CONFIG_VERSION, REVIEW_REQUEST_VERSION,
    REVIEW_RUN_ARTIFACT_VERSION,
};
use std::{
    collections::BTreeMap,
    env, fs,
    path::{Component, Path, PathBuf},
    process::Command,
};

mod eval_harness;
mod local_review;
mod model_catalog;
use eval_harness::eval_harness;
use local_review::{local_review_request_from_diff, LocalReviewArgs};
use model_catalog::refresh_openrouter_matrix;

fn main() -> Result<()> {
    let mut args = env::args().skip(1);
    let Some(command) = args.next() else {
        usage();
        bail!("missing command");
    };

    match command.as_str() {
        "validate" => validate(args.collect()),
        "validate-retirement" => validate_retirement(args.collect()),
        "validate-reviewer-config" => validate_reviewer_config(args.collect()),
        "review" => review_command(args.collect()),
        "review-local" => review_local(args.collect()),
        "github-action-request" => github_action_request(args.collect()),
        "hosted-api-dispatch-fixture" => hosted_api_dispatch_fixture(args.collect()),
        "eval-harness" => eval_harness(args.collect()),
        "propose-reviewer-config" => propose_reviewer_config(args.collect()),
        "refresh-model-catalog" => refresh_model_catalog(args.collect()),
        "import-reviewer-config" => import_reviewer_config(args.collect()),
        "render" => render(args.collect()),
        "render-comments" => render_comments(args.collect()),
        "--help" | "-h" | "help" => {
            usage();
            Ok(())
        }
        _ => {
            usage();
            bail!("unknown command {command:?}");
        }
    }
}

fn validate_retirement(paths: Vec<String>) -> Result<()> {
    if paths.is_empty() {
        bail!("validate-retirement requires at least one inventory path");
    }

    for path in paths {
        let inventory_path = PathBuf::from(&path);
        let inventory = read_retirement_inventory(&inventory_path)?;
        validate_retirement_paths(&inventory, Path::new("."))?;
        println!("{path}: ok");
    }

    Ok(())
}

fn refresh_model_catalog(args: Vec<String>) -> Result<()> {
    let mut matrix = None;
    let mut catalog_source = None;
    let mut out = None;
    let mut raw_out = None;
    let mut observed_at = None;
    let mut index = 0;

    while index < args.len() {
        match args[index].as_str() {
            "--matrix" => {
                matrix = Some(required_arg(&args, index, "--matrix")?);
                index += 2;
            }
            "--catalog-source" => {
                catalog_source = Some(required_arg(&args, index, "--catalog-source")?);
                index += 2;
            }
            "--out" => {
                out = Some(required_arg(&args, index, "--out")?);
                index += 2;
            }
            "--raw-out" => {
                raw_out = Some(required_arg(&args, index, "--raw-out")?);
                index += 2;
            }
            "--observed-at" => {
                observed_at = Some(required_arg(&args, index, "--observed-at")?);
                index += 2;
            }
            other => bail!("unknown refresh-model-catalog argument {other:?}"),
        }
    }

    let matrix_path =
        PathBuf::from(matrix.context("refresh-model-catalog requires --matrix <path>")?);
    let catalog_source =
        catalog_source.context("refresh-model-catalog requires --catalog-source <path-or-url>")?;
    let out_path = PathBuf::from(out.context("refresh-model-catalog requires --out <path>")?);
    let raw_out_path =
        PathBuf::from(raw_out.context("refresh-model-catalog requires --raw-out <path>")?);

    let matrix = read_eval_matrix(&matrix_path)?;
    let observed_at = observed_at.unwrap_or_else(|| matrix.observed_at.clone());
    let raw_catalog = read_catalog_source(&catalog_source)?;
    let refreshed =
        refresh_openrouter_matrix(&matrix, &raw_catalog, &catalog_source, &observed_at)?;

    write_raw(&raw_out_path, &raw_catalog)?;
    write_json(&out_path, &refreshed)?;
    println!("{}", out_path.display());
    Ok(())
}

fn validate_reviewer_config(paths: Vec<String>) -> Result<()> {
    if paths.is_empty() {
        bail!("validate-reviewer-config requires at least one packet path");
    }

    for path in paths {
        let packet = read_reviewer_config_packet(&PathBuf::from(&path))?;
        validate_reviewer_config_packet(&packet)?;
        println!("{path}: ok");
    }

    Ok(())
}

fn validate(paths: Vec<String>) -> Result<()> {
    if paths.is_empty() {
        bail!("validate requires at least one review request path");
    }

    for path in paths {
        validate_document(&PathBuf::from(&path))?;
        println!("{path}: ok");
    }

    Ok(())
}

fn review_command(args: Vec<String>) -> Result<()> {
    let mut fixture = None;
    let mut out = None;
    let mut config = None;
    let mut config_packet = None;
    let mut index = 0;

    while index < args.len() {
        match args[index].as_str() {
            "--fixture" => {
                fixture = Some(required_arg(&args, index, "--fixture")?);
                index += 2;
            }
            "--out" => {
                out = Some(required_arg(&args, index, "--out")?);
                index += 2;
            }
            "--config" => {
                config = Some(required_arg(&args, index, "--config")?);
                index += 2;
            }
            "--config-packet" => {
                config_packet = Some(required_arg(&args, index, "--config-packet")?);
                index += 2;
            }
            other => bail!("unknown review argument {other:?}"),
        }
    }

    let fixture = fixture.context("review requires --fixture <path>")?;
    let out = out.context("review requires --out <dir>")?;
    let config_path = config.map(PathBuf::from);
    let config_packet_path = config_packet.map(PathBuf::from);
    let config = read_review_config_source(
        config_path.as_deref(),
        config_packet_path.as_deref(),
        "review",
    )?;
    let request = read_request(&PathBuf::from(&fixture))?;
    let artifact = review(&request, &config)?;
    let out_dir = PathBuf::from(out);

    fs::create_dir_all(&out_dir)
        .with_context(|| format!("failed to create output dir {}", out_dir.display()))?;

    let artifact_path = out_dir.join("review-run-artifact.json");
    let markdown_path = out_dir.join("review-run.md");
    write_json(&artifact_path, &artifact)?;
    fs::write(&markdown_path, render_markdown(&artifact))
        .with_context(|| format!("failed to write {}", markdown_path.display()))?;

    println!("{}", artifact_path.display());
    Ok(())
}

fn review_local(args: Vec<String>) -> Result<()> {
    let args = LocalReviewArgs::parse(&args)?;
    let request = local_review_request_from_diff(&args)?;
    let config = read_review_config_source(
        args.config.as_deref(),
        args.config_packet.as_deref(),
        "review-local",
    )?;
    let artifact = review(&request, &config)?;

    fs::create_dir_all(&args.out)
        .with_context(|| format!("failed to create output dir {}", args.out.display()))?;

    let request_path = args.out.join("review-request.json");
    let artifact_path = args.out.join("review-run-artifact.json");
    let markdown_path = args.out.join("review-run.md");
    write_json(&request_path, &request)?;
    write_json(&artifact_path, &artifact)?;
    fs::write(&markdown_path, render_markdown(&artifact))
        .with_context(|| format!("failed to write {}", markdown_path.display()))?;

    println!("{}", artifact_path.display());
    Ok(())
}

fn github_action_request(args: Vec<String>) -> Result<()> {
    let mut event = None;
    let mut diff_file = None;
    let mut out = None;
    let mut run_id = None;
    let mut index = 0;

    while index < args.len() {
        match args[index].as_str() {
            "--event" => {
                event = Some(required_arg(&args, index, "--event")?);
                index += 2;
            }
            "--diff-file" => {
                diff_file = Some(required_arg(&args, index, "--diff-file")?);
                index += 2;
            }
            "--out" => {
                out = Some(required_arg(&args, index, "--out")?);
                index += 2;
            }
            "--run-id" => {
                run_id = Some(required_arg(&args, index, "--run-id")?);
                index += 2;
            }
            other => bail!("unknown github-action-request argument {other:?}"),
        }
    }

    let event_path = PathBuf::from(event.context("github-action-request requires --event <path>")?);
    let diff_path =
        PathBuf::from(diff_file.context("github-action-request requires --diff-file <path>")?);
    let out_path = PathBuf::from(out.context("github-action-request requires --out <path>")?);
    let run_id = run_id.unwrap_or_else(default_github_action_run_id);
    let event_json = fs::read_to_string(&event_path)
        .with_context(|| format!("failed to read GitHub event {}", event_path.display()))?;

    if let Some(decision) = github_action_skip_decision_from_event(&event_json)? {
        remove_stale_file(&out_path)?;
        let json = serde_json::to_string_pretty(&decision)?;
        println!("{json}");
        return Ok(());
    }

    let diff = fs::read_to_string(&diff_path)
        .with_context(|| format!("failed to read GitHub diff {}", diff_path.display()))?;

    match github_action_review_decision_from_event(&event_json, &diff, run_id)? {
        GithubActionReviewDecision::Review { request } => {
            write_json(&out_path, &request)?;
            println!("{}", out_path.display());
        }
        decision @ GithubActionReviewDecision::Skip { .. } => {
            remove_stale_file(&out_path)?;
            let json = serde_json::to_string_pretty(&decision)?;
            println!("{json}");
        }
    }

    Ok(())
}

fn hosted_api_dispatch_fixture(args: Vec<String>) -> Result<()> {
    let mut transcript = None;
    let mut out = None;
    let mut index = 0;

    while index < args.len() {
        match args[index].as_str() {
            "--transcript" => {
                transcript = Some(required_arg(&args, index, "--transcript")?);
                index += 2;
            }
            "--out" => {
                out = Some(required_arg(&args, index, "--out")?);
                index += 2;
            }
            other => bail!("unknown hosted-api-dispatch-fixture argument {other:?}"),
        }
    }

    let transcript_path = PathBuf::from(
        transcript.context("hosted-api-dispatch-fixture requires --transcript <path>")?,
    );
    let out_path = PathBuf::from(out.context("hosted-api-dispatch-fixture requires --out <path>")?);
    let transcript = read_hosted_api_dispatch_transcript(&transcript_path)?;
    let decision = run_hosted_api_dispatch_fixture(&transcript)?;
    write_json(&out_path, &decision)?;
    println!("{}", out_path.display());
    Ok(())
}

fn default_github_action_run_id() -> String {
    match (env::var("GITHUB_RUN_ID"), env::var("GITHUB_RUN_ATTEMPT")) {
        (Ok(run_id), Ok(attempt)) if !run_id.trim().is_empty() && !attempt.trim().is_empty() => {
            format!("{run_id}-{attempt}")
        }
        (Ok(run_id), _) if !run_id.trim().is_empty() => run_id,
        _ => "github-actions-local".to_string(),
    }
}

fn import_reviewer_config(args: Vec<String>) -> Result<()> {
    let mut packet_path = None;
    let mut baseline_path = None;
    let mut fixture_path = None;
    let mut out_path = None;
    let mut dry_run = false;
    let mut index = 0;

    while index < args.len() {
        match args[index].as_str() {
            "--dry-run" => {
                dry_run = true;
                index += 1;
            }
            "--baseline" => {
                baseline_path = Some(required_arg(&args, index, "--baseline")?);
                index += 2;
            }
            "--fixture" => {
                fixture_path = Some(required_arg(&args, index, "--fixture")?);
                index += 2;
            }
            "--out" => {
                out_path = Some(required_arg(&args, index, "--out")?);
                index += 2;
            }
            value if packet_path.is_none() => {
                packet_path = Some(value.to_string());
                index += 1;
            }
            other => bail!("unknown import-reviewer-config argument {other:?}"),
        }
    }

    if !dry_run {
        bail!("import-reviewer-config currently requires --dry-run");
    }
    let packet_path = packet_path.context("import-reviewer-config requires <packet>")?;
    let packet = read_reviewer_config_packet(&PathBuf::from(&packet_path))?;
    let baseline = match baseline_path {
        Some(path) => read_config(&PathBuf::from(path))?,
        None => default_config(),
    };
    let fixture = match fixture_path {
        Some(path) => read_request(&PathBuf::from(path))?,
        None => reviewer_config_promotion_fixture_request(),
    };
    let report = reviewer_config_import_dry_run(&packet, &baseline, &fixture)?;

    if let Some(out_path) = out_path {
        let path = PathBuf::from(out_path);
        write_json(&path, &report)?;
        println!("{}", path.display());
    } else {
        let json = serde_json::to_string_pretty(&report)?;
        println!("{json}");
    }

    Ok(())
}

fn propose_reviewer_config(args: Vec<String>) -> Result<()> {
    let mut report = None;
    let mut matrix = None;
    let mut suite = None;
    let mut evidence_dir = None;
    let mut out = None;
    let mut index = 0;

    while index < args.len() {
        match args[index].as_str() {
            "--report" => {
                report = Some(required_arg(&args, index, "--report")?);
                index += 2;
            }
            "--matrix" => {
                matrix = Some(required_arg(&args, index, "--matrix")?);
                index += 2;
            }
            "--suite" => {
                suite = Some(required_arg(&args, index, "--suite")?);
                index += 2;
            }
            "--evidence-dir" => {
                evidence_dir = Some(required_arg(&args, index, "--evidence-dir")?);
                index += 2;
            }
            "--out" => {
                out = Some(required_arg(&args, index, "--out")?);
                index += 2;
            }
            other => bail!("unknown propose-reviewer-config argument {other:?}"),
        }
    }

    let report_path =
        PathBuf::from(report.context("propose-reviewer-config requires --report <path>")?);
    let matrix_path =
        PathBuf::from(matrix.context("propose-reviewer-config requires --matrix <path>")?);
    let suite_path =
        PathBuf::from(suite.context("propose-reviewer-config requires --suite <path>")?);
    let evidence_dir_path = PathBuf::from(
        evidence_dir.context("propose-reviewer-config requires --evidence-dir <dir>")?,
    );
    let out_path = PathBuf::from(out.context("propose-reviewer-config requires --out <path>")?);
    remove_stale_file(&out_path)?;
    let report = read_harness_model_evaluation_report(&report_path)?;
    let matrix = read_eval_matrix(&matrix_path)?;
    let suite = read_eval_suite(&suite_path)?;
    let transcripts = read_eval_evidence_transcripts(&report, &evidence_dir_path)?;
    let packet =
        reviewer_config_candidate_from_eval_report(&report, &matrix, &suite, &transcripts)?;

    write_json(&out_path, &packet)?;
    println!("{}", out_path.display());
    Ok(())
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

fn read_review_config_source(
    config: Option<&Path>,
    config_packet: Option<&Path>,
    command: &str,
) -> Result<ReviewConfig> {
    match (config, config_packet) {
        (Some(_), Some(_)) => {
            bail!("{command} accepts either --config or --config-packet, not both")
        }
        (Some(path), None) => read_config(path),
        (None, Some(path)) => Ok(read_reviewer_config_packet(path)?.config),
        (None, None) => Ok(default_config()),
    }
}

fn render(args: Vec<String>) -> Result<()> {
    if args.len() != 1 {
        bail!("render requires exactly one review-run artifact path");
    }

    let artifact = read_artifact(&PathBuf::from(&args[0]))?;
    print!("{}", render_markdown(&artifact));
    Ok(())
}

fn render_comments(args: Vec<String>) -> Result<()> {
    if args.len() != 1 {
        bail!("render-comments requires exactly one review-run artifact path");
    }

    let artifact = read_artifact(&PathBuf::from(&args[0]))?;
    let comments = render_inline_comment_candidates(&artifact);
    for comment in &comments {
        comment.validate()?;
    }
    let json = serde_json::to_string_pretty(&comments)?;
    println!("{json}");
    Ok(())
}

fn validate_document(path: &PathBuf) -> Result<()> {
    let raw =
        fs::read_to_string(path).with_context(|| format!("failed to read {}", path.display()))?;
    let value: serde_json::Value = serde_json::from_str(&raw)
        .with_context(|| format!("failed to parse {}", path.display()))?;
    let schema_version = value
        .get("schema_version")
        .and_then(|value| value.as_str())
        .with_context(|| format!("{} is missing schema_version", path.display()))?;

    match schema_version {
        REVIEW_REQUEST_VERSION => {
            let request: ReviewRequest = serde_json::from_value(value)?;
            request.validate()?;
        }
        REVIEW_CONFIG_VERSION => {
            let config: ReviewConfig = serde_json::from_value(value)?;
            config.validate()?;
        }
        REVIEWER_ARTIFACT_VERSION => {
            let artifact: ReviewerArtifact = serde_json::from_value(value)?;
            artifact.validate()?;
        }
        REVIEW_RUN_ARTIFACT_VERSION => {
            let artifact: ReviewRunArtifact = serde_json::from_value(value)?;
            artifact.validate()?;
        }
        INLINE_COMMENT_CANDIDATE_VERSION => {
            let candidate: InlineCommentCandidate = serde_json::from_value(value)?;
            candidate.validate()?;
        }
        EVAL_TASK_SUITE_VERSION => {
            let suite: EvalTaskSuite = serde_json::from_value(value)?;
            suite.validate()?;
        }
        HARNESS_PROFILE_VERSION => {
            let profile: HarnessProfile = serde_json::from_value(value)?;
            profile.validate()?;
        }
        MODEL_CANDIDATE_VERSION => {
            let model: ModelCandidate = serde_json::from_value(value)?;
            model.validate()?;
        }
        HARNESS_MODEL_MATRIX_VERSION => {
            let matrix: HarnessModelMatrix = serde_json::from_value(value)?;
            matrix.validate()?;
        }
        HARNESS_MODEL_EVALUATION_REPORT_VERSION => {
            let report: HarnessModelEvaluationReport = serde_json::from_value(value)?;
            report.validate()?;
        }
        PEER_HARNESS_COMMAND_PROFILES_VERSION => {
            let profiles: PeerHarnessCommandProfiles = serde_json::from_value(value)?;
            profiles.validate()?;
        }
        PEER_HARNESS_EXECUTION_PLAN_VERSION => {
            let plan: PeerHarnessExecutionPlan = serde_json::from_value(value)?;
            plan.validate()?;
        }
        REVIEWER_CONFIG_PACKET_VERSION => {
            let packet: ReviewerConfigPacket = serde_json::from_value(value)?;
            validate_reviewer_config_packet(&packet)?;
        }
        REVIEWER_CONFIG_IMPORT_REPORT_VERSION => {
            let report: ReviewerConfigImportReport = serde_json::from_value(value)?;
            report.validate()?;
        }
        LEGACY_SURFACE_INVENTORY_VERSION => {
            let inventory: LegacySurfaceInventory = serde_json::from_value(value)?;
            inventory.validate()?;
        }
        other => bail!("unsupported schema_version {other:?} in {}", path.display()),
    }

    Ok(())
}

fn read_request(path: &PathBuf) -> Result<ReviewRequest> {
    let raw = fs::read_to_string(path)
        .with_context(|| format!("failed to read review request {}", path.display()))?;
    let request: ReviewRequest = serde_json::from_str(&raw)
        .with_context(|| format!("failed to parse review request {}", path.display()))?;
    Ok(request)
}

fn read_artifact(path: &PathBuf) -> Result<ReviewRunArtifact> {
    let raw = fs::read_to_string(path)
        .with_context(|| format!("failed to read artifact {}", path.display()))?;
    let artifact: ReviewRunArtifact = serde_json::from_str(&raw)
        .with_context(|| format!("failed to parse artifact {}", path.display()))?;
    artifact.validate()?;
    Ok(artifact)
}

fn read_eval_suite(path: &PathBuf) -> Result<EvalTaskSuite> {
    let raw = fs::read_to_string(path)
        .with_context(|| format!("failed to read eval suite {}", path.display()))?;
    let suite: EvalTaskSuite = serde_json::from_str(&raw)
        .with_context(|| format!("failed to parse eval suite {}", path.display()))?;
    suite.validate()?;
    Ok(suite)
}

fn read_eval_matrix(path: &PathBuf) -> Result<HarnessModelMatrix> {
    let raw = fs::read_to_string(path)
        .with_context(|| format!("failed to read eval matrix {}", path.display()))?;
    let matrix: HarnessModelMatrix = serde_json::from_str(&raw)
        .with_context(|| format!("failed to parse eval matrix {}", path.display()))?;
    matrix.validate()?;
    Ok(matrix)
}

fn read_harness_model_evaluation_report(path: &PathBuf) -> Result<HarnessModelEvaluationReport> {
    let raw = fs::read_to_string(path)
        .with_context(|| format!("failed to read eval report {}", path.display()))?;
    let report: HarnessModelEvaluationReport = serde_json::from_str(&raw)
        .with_context(|| format!("failed to parse eval report {}", path.display()))?;
    report.validate()?;
    Ok(report)
}

fn read_eval_evidence_transcripts(
    report: &HarnessModelEvaluationReport,
    evidence_dir: &Path,
) -> Result<BTreeMap<String, String>> {
    let mut transcripts = BTreeMap::new();
    for cell in &report.cells {
        let transcript_path = safe_evidence_relative_path(&cell.transcript_path)?;
        let path = evidence_dir.join(transcript_path);
        let transcript = fs::read_to_string(&path)
            .with_context(|| format!("failed to read eval transcript {}", path.display()))?;
        if transcripts
            .insert(cell.transcript_path.clone(), transcript)
            .is_some()
        {
            bail!("duplicate eval transcript path {:?}", cell.transcript_path);
        }
    }
    Ok(transcripts)
}

fn safe_evidence_relative_path(path: &str) -> Result<&Path> {
    let path = Path::new(path);
    if path.is_absolute()
        || path
            .components()
            .any(|component| matches!(component, Component::ParentDir | Component::Prefix(_)))
    {
        bail!("eval transcript path must be relative and stay inside evidence dir");
    }
    Ok(path)
}

fn read_config(path: &Path) -> Result<ReviewConfig> {
    let raw = fs::read_to_string(path)
        .with_context(|| format!("failed to read review config {}", path.display()))?;
    let config: ReviewConfig = serde_json::from_str(&raw)
        .with_context(|| format!("failed to parse review config {}", path.display()))?;
    config.validate()?;
    Ok(config)
}

fn read_retirement_inventory(path: &PathBuf) -> Result<LegacySurfaceInventory> {
    let raw = fs::read_to_string(path).with_context(|| {
        format!(
            "failed to read legacy retirement inventory {}",
            path.display()
        )
    })?;
    let inventory: LegacySurfaceInventory = serde_json::from_str(&raw).with_context(|| {
        format!(
            "failed to parse legacy retirement inventory {}",
            path.display()
        )
    })?;
    inventory.validate()?;
    Ok(inventory)
}

fn read_hosted_api_dispatch_transcript(path: &PathBuf) -> Result<HostedApiDispatchTranscript> {
    let raw = fs::read_to_string(path)
        .with_context(|| format!("failed to read hosted API transcript {}", path.display()))?;
    serde_json::from_str(&raw)
        .with_context(|| format!("failed to parse hosted API transcript {}", path.display()))
}

fn read_catalog_source(source: &str) -> Result<String> {
    if source.starts_with("https://") || source.starts_with("http://") {
        return fetch_catalog_url(source);
    }
    fs::read_to_string(source).with_context(|| format!("failed to read catalog source {source}"))
}

fn fetch_catalog_url(url: &str) -> Result<String> {
    let output = Command::new("curl")
        .args(["-fsSL", "--max-time", "30", url])
        .output()
        .with_context(|| format!("failed to launch curl for {url}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        bail!("curl failed for {url}: {}", stderr.trim());
    }
    String::from_utf8(output.stdout)
        .with_context(|| format!("catalog response was not UTF-8: {url}"))
}

fn read_reviewer_config_packet(path: &Path) -> Result<ReviewerConfigPacket> {
    let raw = fs::read_to_string(path)
        .with_context(|| format!("failed to read reviewer config packet {}", path.display()))?;
    let packet: ReviewerConfigPacket = serde_json::from_str(&raw)
        .with_context(|| format!("failed to parse reviewer config packet {}", path.display()))?;
    validate_reviewer_config_packet(&packet)?;
    Ok(packet)
}

fn validate_retirement_paths(inventory: &LegacySurfaceInventory, root: &Path) -> Result<()> {
    for surface in &inventory.surfaces {
        for path in &surface.paths {
            let path = root.join(path);
            if !path.exists() {
                bail!(
                    "legacy surface {} references missing path {}",
                    surface.surface_id,
                    path.display()
                );
            }
        }
    }
    Ok(())
}

fn probe_harness(profile: &HarnessProfile) -> HarnessProbe {
    match Command::new(&profile.command).arg("--version").output() {
        Ok(output) if output.status.success() => {
            let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
            let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
            HarnessProbe {
                harness_id: profile.harness_id.clone(),
                available: true,
                version: if stdout.is_empty() {
                    if stderr.is_empty() {
                        profile.version.clone()
                    } else {
                        Some(stderr)
                    }
                } else {
                    Some(stdout)
                },
                path: find_on_path(&profile.command).or_else(|| profile.path.clone()),
                failure_reason: None,
            }
        }
        Ok(output) => HarnessProbe {
            harness_id: profile.harness_id.clone(),
            available: false,
            version: None,
            path: find_on_path(&profile.command).or_else(|| profile.path.clone()),
            failure_reason: Some(format!(
                "{} --version exited with {}",
                profile.command, output.status
            )),
        },
        Err(error) => HarnessProbe {
            harness_id: profile.harness_id.clone(),
            available: false,
            version: None,
            path: find_on_path(&profile.command).or_else(|| profile.path.clone()),
            failure_reason: Some(format!("{} unavailable: {error}", profile.command)),
        },
    }
}

fn find_on_path(command: &str) -> Option<String> {
    let command_path = Path::new(command);
    if command_path.components().count() > 1 {
        return command_path.exists().then(|| command.to_string());
    }

    env::var_os("PATH").and_then(|path| {
        env::split_paths(&path)
            .map(|dir| dir.join(command))
            .find(|candidate| candidate.exists())
            .map(|candidate| candidate.display().to_string())
    })
}

fn scan_stale_models(matrix: &HarnessModelMatrix) -> Result<Vec<StaleModelFinding>> {
    let mut findings = Vec::new();
    for scan_path in &matrix.drift_scan_paths {
        scan_path_for_patterns(
            Path::new(scan_path),
            &matrix.stale_model_patterns,
            &mut findings,
        )?;
    }
    findings.sort_by(|left, right| {
        (&left.path, left.line, &left.pattern, &left.text).cmp(&(
            &right.path,
            right.line,
            &right.pattern,
            &right.text,
        ))
    });
    Ok(findings)
}

fn scan_path_for_patterns(
    path: &Path,
    patterns: &[String],
    findings: &mut Vec<StaleModelFinding>,
) -> Result<()> {
    if !path.exists() {
        bail!(
            "configured drift scan path does not exist: {}",
            path.display()
        );
    }
    if path.is_dir() {
        let mut children = Vec::new();
        for entry in fs::read_dir(path)
            .with_context(|| format!("failed to read scan dir {}", path.display()))?
        {
            children.push(entry?.path());
        }
        children.sort();
        for child in children {
            if child.file_name().is_some_and(|name| {
                name == ".git"
                    || name == "_build"
                    || name == "deps"
                    || name == "node_modules"
                    || name == "target"
                    || name == "tmp"
            }) {
                continue;
            }
            scan_path_for_patterns(&child, patterns, findings)?;
        }
        return Ok(());
    }

    let raw = fs::read_to_string(path)
        .with_context(|| format!("failed to read scan file {}", path.display()))?;
    for (index, line) in raw.lines().enumerate() {
        for pattern in patterns {
            if line.contains(pattern) {
                findings.push(StaleModelFinding {
                    pattern: pattern.clone(),
                    path: path.display().to_string(),
                    line: index as u64 + 1,
                    text: line.trim().to_string(),
                });
            }
        }
    }
    Ok(())
}

fn write_json<T: serde::Serialize>(path: &PathBuf, value: &T) -> Result<()> {
    let json = serde_json::to_string_pretty(value)?;
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        fs::create_dir_all(parent)
            .with_context(|| format!("failed to create output dir {}", parent.display()))?;
    }
    fs::write(path, format!("{json}\n"))
        .with_context(|| format!("failed to write {}", path.display()))
}

fn remove_stale_file(path: &Path) -> Result<()> {
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => {
            Err(error).with_context(|| format!("failed to remove stale file {}", path.display()))
        }
    }
}

fn write_raw(path: &PathBuf, raw: &str) -> Result<()> {
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        fs::create_dir_all(parent)
            .with_context(|| format!("failed to create output dir {}", parent.display()))?;
    }
    fs::write(path, raw).with_context(|| format!("failed to write {}", path.display()))
}

fn usage() {
    eprintln!(
        "usage:\n  cerberus-cli validate <schema.json>...\n  cerberus-cli validate-retirement <legacy-surface-inventory.json>...\n  cerberus-cli validate-reviewer-config <packet.json>...\n  cerberus-cli import-reviewer-config <packet.json> --dry-run [--baseline <review-config.json>] [--fixture <review-request.json>] [--out <report.json>]\n  cerberus-cli propose-reviewer-config --report <HarnessModelEvaluationReport.v1.json> --matrix <HarnessModelMatrix.v1.json> --suite <EvalTaskSuite.v1.json> --evidence-dir <eval-output-dir> --out <ReviewerConfigPacket.v1.json>\n  cerberus-cli review --fixture <review-request.json> --out <dir> [--config <review-config.json> | --config-packet <ReviewerConfigPacket.v1.json>]\n  cerberus-cli review-local --diff-file <diff> --out <dir> [--config <review-config.json> | --config-packet <ReviewerConfigPacket.v1.json>] [--repo-path <path>] [--request-id <id>] [--title <title>]\n  cerberus-cli github-action-request --event <pull_request_event.json> --diff-file <diff> --out <review-request.json> [--run-id <id>]\n  cerberus-cli hosted-api-dispatch-fixture --transcript <hosted-api-transcript.json> --out <decision.json>\n  cerberus-cli eval-harness --suite <eval-suite.json> --matrix <matrix.json> --out <dir> [--execution-mode offline-contract|live-peer] [--peer-profiles <PeerHarnessCommandProfiles.v3.json>]\n  cerberus-cli refresh-model-catalog --matrix <matrix.json> --catalog-source <path-or-url> --out <matrix.json> --raw-out <raw.json> [--observed-at <stamp>]\n  cerberus-cli render <review-run-artifact.json>\n  cerberus-cli render-comments <review-run-artifact.json>"
    );
}
