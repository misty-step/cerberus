use anyhow::{bail, Context, Result};
use cerberus_adapter::changed_files_from_git_diff;
use cerberus_schema::{
    Caller, Change, ReviewContext, ReviewPolicy, ReviewRequest, ReviewSource,
    REVIEW_REQUEST_VERSION,
};
use std::{collections::BTreeMap, fs, path::PathBuf};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LocalReviewArgs {
    pub diff_file: PathBuf,
    pub out: PathBuf,
    pub config: Option<PathBuf>,
    pub config_packet: Option<PathBuf>,
    pub repo_path: Option<String>,
    pub request_id: String,
    pub title: String,
}

impl LocalReviewArgs {
    pub fn parse(args: &[String]) -> Result<Self> {
        let mut diff_file = None;
        let mut out = None;
        let mut config = None;
        let mut config_packet = None;
        let mut repo_path = None;
        let mut request_id = None;
        let mut title = None;
        let mut index = 0;

        while index < args.len() {
            match args[index].as_str() {
                "--diff-file" => {
                    diff_file = Some(PathBuf::from(required_value(args, index, "--diff-file")?));
                    index += 2;
                }
                "--out" => {
                    out = Some(PathBuf::from(required_value(args, index, "--out")?));
                    index += 2;
                }
                "--config" => {
                    config = Some(PathBuf::from(required_value(args, index, "--config")?));
                    index += 2;
                }
                "--config-packet" => {
                    config_packet = Some(PathBuf::from(required_value(
                        args,
                        index,
                        "--config-packet",
                    )?));
                    index += 2;
                }
                "--repo-path" => {
                    repo_path = Some(required_value(args, index, "--repo-path")?);
                    index += 2;
                }
                "--request-id" => {
                    request_id = Some(required_value(args, index, "--request-id")?);
                    index += 2;
                }
                "--title" => {
                    title = Some(required_value(args, index, "--title")?);
                    index += 2;
                }
                other => bail!("unknown review-local argument {other:?}"),
            }
        }

        if config.is_some() && config_packet.is_some() {
            bail!("review-local accepts either --config or --config-packet, not both");
        }
        let diff_file = diff_file.context("review-local requires --diff-file <path>")?;
        let request_id = request_id.unwrap_or_else(|| {
            let stem = diff_file
                .file_stem()
                .and_then(|value| value.to_str())
                .unwrap_or("local-diff");
            format!("local-diff-{stem}")
        });

        Ok(Self {
            diff_file,
            out: out.context("review-local requires --out <dir>")?,
            config,
            config_packet,
            repo_path,
            request_id,
            title: title.unwrap_or_else(|| "Local diff review".to_string()),
        })
    }
}

pub fn local_review_request_from_diff(args: &LocalReviewArgs) -> Result<ReviewRequest> {
    let diff = fs::read_to_string(&args.diff_file)
        .with_context(|| format!("failed to read local diff {}", args.diff_file.display()))?;
    let files = changed_files_from_git_diff(&diff)?;
    let mut metadata = BTreeMap::new();
    metadata.insert(
        "diff_file".to_string(),
        args.diff_file.display().to_string(),
    );

    let request = ReviewRequest {
        schema_version: REVIEW_REQUEST_VERSION.to_string(),
        request_id: args.request_id.clone(),
        source: ReviewSource::LocalDiff {
            repo_path: args.repo_path.clone(),
        },
        change: Change {
            title: args.title.clone(),
            description: Some(format!(
                "Rust local review generated from {}.",
                args.diff_file.display()
            )),
            base_ref: None,
            head_ref: None,
            head_sha: None,
            diff,
            files,
        },
        context: ReviewContext {
            summary: Some("Rust local diff review.".to_string()),
            acceptance: vec![],
            linked_artifacts: vec![],
            metadata,
        },
        caller: Caller {
            name: "cerberus-cli".to_string(),
            run_id: args.request_id.clone(),
        },
        policy: ReviewPolicy::default(),
    };
    request.validate()?;
    Ok(request)
}

fn required_value(args: &[String], index: usize, flag: &'static str) -> Result<String> {
    args.get(index + 1)
        .filter(|value| !value.starts_with("--"))
        .cloned()
        .with_context(|| format!("{flag} requires a value"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn local_review_builds_valid_request() {
        let root =
            std::env::temp_dir().join(format!("cerberus-local-review-{}", std::process::id()));
        fs::create_dir_all(&root).expect("temp dir created");
        let diff_file = root.join("local.diff");
        fs::write(
            &diff_file,
            "diff --git a/src/lib.rs b/src/lib.rs\n--- a/src/lib.rs\n+++ b/src/lib.rs\n@@ -1 +1,2 @@\n fn review() {}\n+// CERBERUS_FAKE_FINDING\n",
        )
        .expect("diff fixture written");
        let args = LocalReviewArgs {
            diff_file: diff_file.clone(),
            out: root.join("out"),
            config: None,
            config_packet: None,
            repo_path: Some(".".to_string()),
            request_id: "local-test".to_string(),
            title: "Local test".to_string(),
        };

        let request = local_review_request_from_diff(&args).expect("request builds");

        assert_eq!(request.request_id, "local-test");
        assert_eq!(request.change.files[0].path, "src/lib.rs");
        assert_eq!(request.change.files[0].additions, 1);
        request.validate().expect("request validates");
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn local_review_args_require_diff_and_out() {
        let error = LocalReviewArgs::parse(&[]).expect_err("missing diff rejects");
        assert!(error.to_string().contains("--diff-file"));

        let error = LocalReviewArgs::parse(&["--diff-file".to_string(), "local.diff".to_string()])
            .expect_err("missing out rejects");
        assert!(error.to_string().contains("--out"));
    }

    #[test]
    fn local_review_args_accept_config_packet_source() {
        let args = LocalReviewArgs::parse(&[
            "--diff-file".to_string(),
            "local.diff".to_string(),
            "--out".to_string(),
            "out".to_string(),
            "--config-packet".to_string(),
            "packet.json".to_string(),
        ])
        .expect("config packet source parses");

        assert_eq!(args.config, None);
        assert_eq!(args.config_packet, Some(PathBuf::from("packet.json")));
    }

    #[test]
    fn local_review_args_reject_conflicting_config_sources() {
        let error = LocalReviewArgs::parse(&[
            "--diff-file".to_string(),
            "local.diff".to_string(),
            "--out".to_string(),
            "out".to_string(),
            "--config".to_string(),
            "config.json".to_string(),
            "--config-packet".to_string(),
            "packet.json".to_string(),
        ])
        .expect_err("conflicting config sources reject");

        assert!(error
            .to_string()
            .contains("either --config or --config-packet"));
    }
}
