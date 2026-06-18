use anyhow::{bail, Context, Result};
use cerberus_core::{default_config, render_inline_comment_candidates, render_markdown, review};
use cerberus_schema::{
    InlineCommentCandidate, ReviewConfig, ReviewRequest, ReviewRunArtifact, ReviewerArtifact,
    INLINE_COMMENT_CANDIDATE_VERSION, REVIEWER_ARTIFACT_VERSION, REVIEW_CONFIG_VERSION,
    REVIEW_REQUEST_VERSION, REVIEW_RUN_ARTIFACT_VERSION,
};
use std::{env, fs, path::PathBuf};

fn main() -> Result<()> {
    let mut args = env::args().skip(1);
    let Some(command) = args.next() else {
        usage();
        bail!("missing command");
    };

    match command.as_str() {
        "validate" => validate(args.collect()),
        "review" => review_command(args.collect()),
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

fn read_config(path: &PathBuf) -> Result<ReviewConfig> {
    let raw = fs::read_to_string(path)
        .with_context(|| format!("failed to read review config {}", path.display()))?;
    let config: ReviewConfig = serde_json::from_str(&raw)
        .with_context(|| format!("failed to parse review config {}", path.display()))?;
    config.validate()?;
    Ok(config)
}

fn write_json<T: serde::Serialize>(path: &PathBuf, value: &T) -> Result<()> {
    let json = serde_json::to_string_pretty(value)?;
    fs::write(path, format!("{json}\n"))
        .with_context(|| format!("failed to write {}", path.display()))
}

fn usage() {
    eprintln!(
        "usage:\n  cerberus-cli validate <review-request.json>...\n  cerberus-cli review --fixture <review-request.json> --out <dir> [--config <review-config.json>]\n  cerberus-cli render <review-run-artifact.json>\n  cerberus-cli render-comments <review-run-artifact.json>"
    );
}
