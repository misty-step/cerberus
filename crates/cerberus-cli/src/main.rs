use anyhow::{bail, Context, Result};
use cerberus_core::{
    default_config, evaluate_harness_model_matrix, render_inline_comment_candidates,
    render_markdown, review, HarnessProbe,
};
use cerberus_schema::{
    EvalTaskSuite, HarnessModelEvaluationReport, HarnessModelMatrix, HarnessProfile,
    InlineCommentCandidate, ModelCandidate, ReviewConfig, ReviewRequest, ReviewRunArtifact,
    ReviewerArtifact, StaleModelFinding, EVAL_TASK_SUITE_VERSION,
    HARNESS_MODEL_EVALUATION_REPORT_VERSION, HARNESS_MODEL_MATRIX_VERSION, HARNESS_PROFILE_VERSION,
    INLINE_COMMENT_CANDIDATE_VERSION, MODEL_CANDIDATE_VERSION, REVIEWER_ARTIFACT_VERSION,
    REVIEW_CONFIG_VERSION, REVIEW_REQUEST_VERSION, REVIEW_RUN_ARTIFACT_VERSION,
};
use std::{
    collections::BTreeSet,
    env, fs,
    path::{Path, PathBuf},
    process::Command,
};

fn main() -> Result<()> {
    let mut args = env::args().skip(1);
    let Some(command) = args.next() else {
        usage();
        bail!("missing command");
    };

    match command.as_str() {
        "validate" => validate(args.collect()),
        "review" => review_command(args.collect()),
        "eval-harness" => eval_harness(args.collect()),
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
    let mut index = 0;

    while index < args.len() {
        match args[index].as_str() {
            "--fixture" => {
                fixture = args.get(index + 1).cloned();
                index += 2;
            }
            "--out" => {
                out = args.get(index + 1).cloned();
                index += 2;
            }
            "--config" => {
                config = args.get(index + 1).cloned();
                index += 2;
            }
            other => bail!("unknown review argument {other:?}"),
        }
    }

    let fixture = fixture.context("review requires --fixture <path>")?;
    let out = out.context("review requires --out <dir>")?;
    let request = read_request(&PathBuf::from(&fixture))?;
    let config = match config {
        Some(path) => read_config(&PathBuf::from(path))?,
        None => default_config(),
    };
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

fn eval_harness(args: Vec<String>) -> Result<()> {
    let mut suite = None;
    let mut matrix = None;
    let mut out = None;
    let mut index = 0;

    while index < args.len() {
        match args[index].as_str() {
            "--suite" => {
                suite = args.get(index + 1).cloned();
                index += 2;
            }
            "--matrix" => {
                matrix = args.get(index + 1).cloned();
                index += 2;
            }
            "--out" => {
                out = args.get(index + 1).cloned();
                index += 2;
            }
            other => bail!("unknown eval-harness argument {other:?}"),
        }
    }

    let suite_path = PathBuf::from(suite.context("eval-harness requires --suite <path>")?);
    let matrix_path = PathBuf::from(matrix.context("eval-harness requires --matrix <path>")?);
    let out_dir = PathBuf::from(out.context("eval-harness requires --out <dir>")?);
    let suite = read_eval_suite(&suite_path)?;
    let matrix = read_eval_matrix(&matrix_path)?;
    let probes = matrix
        .harnesses
        .iter()
        .map(probe_harness)
        .collect::<Vec<_>>();
    let stale_model_findings = scan_stale_models(&matrix)?;
    let output = evaluate_harness_model_matrix(&suite, &matrix, &probes, stale_model_findings)?;

    fs::create_dir_all(&out_dir)
        .with_context(|| format!("failed to create output dir {}", out_dir.display()))?;
    let mut transcript_paths = BTreeSet::new();
    for (relative_path, transcript) in &output.transcripts {
        if !transcript_paths.insert(relative_path.as_str()) {
            bail!("duplicate transcript path {relative_path:?}");
        }
        let path = out_dir.join(relative_path);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .with_context(|| format!("failed to create transcript dir {}", parent.display()))?;
        }
        fs::write(&path, transcript)
            .with_context(|| format!("failed to write transcript {}", path.display()))?;
    }

    let report_path = out_dir.join("report.json");
    write_json(&report_path, &output.report)?;
    println!("{}", report_path.display());
    Ok(())
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

fn read_config(path: &PathBuf) -> Result<ReviewConfig> {
    let raw = fs::read_to_string(path)
        .with_context(|| format!("failed to read review config {}", path.display()))?;
    let config: ReviewConfig = serde_json::from_str(&raw)
        .with_context(|| format!("failed to parse review config {}", path.display()))?;
    config.validate()?;
    Ok(config)
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
    fs::write(path, format!("{json}\n"))
        .with_context(|| format!("failed to write {}", path.display()))
}

fn usage() {
    eprintln!(
        "usage:\n  cerberus-cli validate <schema.json>...\n  cerberus-cli review --fixture <review-request.json> --out <dir> [--config <review-config.json>]\n  cerberus-cli eval-harness --suite <eval-suite.json> --matrix <matrix.json> --out <dir>\n  cerberus-cli render <review-run-artifact.json>\n  cerberus-cli render-comments <review-run-artifact.json>"
    );
}
