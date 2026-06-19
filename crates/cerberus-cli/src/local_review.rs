use anyhow::{bail, Context, Result};
use cerberus_schema::{
    Caller, Change, ChangedFile, FileStatus, ReviewContext, ReviewPolicy, ReviewRequest,
    ReviewSource, REVIEW_REQUEST_VERSION,
};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::PathBuf,
};

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

fn changed_files_from_git_diff(diff: &str) -> Result<Vec<ChangedFile>> {
    if diff.trim().is_empty() {
        bail!("local diff is empty");
    }

    let mut files = Vec::new();
    let mut current = None;
    for line in diff.lines() {
        if let Some(path) = parse_diff_git_path(line)? {
            finish_file(&mut files, current.take())?;
            current = Some(FileAccumulator::new(path));
            continue;
        }

        let Some(file) = current.as_mut() else {
            if line.trim().is_empty() {
                continue;
            }
            bail!("local diff must start with a diff --git header");
        };

        if line.starts_with("new file mode ") {
            file.status = FileStatus::Added;
        } else if line.starts_with("deleted file mode ") {
            file.status = FileStatus::Deleted;
        } else if let Some(path) = line.strip_prefix("rename to ") {
            file.path = non_empty_path(path, "rename to")?;
            file.status = FileStatus::Renamed;
        } else if let Some(path) = line.strip_prefix("copy to ") {
            file.path = non_empty_path(path, "copy to")?;
            file.status = FileStatus::Copied;
        } else if line.starts_with('+') && !line.starts_with("+++") {
            file.additions += 1;
        } else if line.starts_with('-') && !line.starts_with("---") {
            file.deletions += 1;
        }
    }
    finish_file(&mut files, current)?;

    if files.is_empty() {
        bail!("local diff did not contain any changed files");
    }
    let mut seen = BTreeSet::new();
    for file in &files {
        if !seen.insert(file.path.as_str()) {
            bail!("local diff contains duplicate file path {:?}", file.path);
        }
    }
    Ok(files)
}

fn parse_diff_git_path(line: &str) -> Result<Option<String>> {
    let Some(rest) = line.strip_prefix("diff --git ") else {
        return Ok(None);
    };
    let mut parts = rest.split_whitespace();
    let _old = parts
        .next()
        .context("diff --git header is missing old path")?;
    let new = parts
        .next()
        .context("diff --git header is missing new path")?;
    if parts.next().is_some() {
        bail!("diff --git header contains unsupported whitespace in paths");
    }
    let Some(path) = new.strip_prefix("b/") else {
        bail!("diff --git new path must start with b/");
    };
    Ok(Some(non_empty_path(path, "diff --git")?))
}

fn non_empty_path(path: &str, field: &'static str) -> Result<String> {
    if path.trim().is_empty() {
        bail!("{field} path must not be empty");
    }
    Ok(path.to_string())
}

fn finish_file(files: &mut Vec<ChangedFile>, file: Option<FileAccumulator>) -> Result<()> {
    let Some(file) = file else {
        return Ok(());
    };
    if file.path.trim().is_empty() {
        bail!("changed file path must not be empty");
    }
    files.push(ChangedFile {
        path: file.path,
        status: file.status,
        additions: file.additions,
        deletions: file.deletions,
    });
    Ok(())
}

fn required_value(args: &[String], index: usize, flag: &'static str) -> Result<String> {
    args.get(index + 1)
        .filter(|value| !value.starts_with("--"))
        .cloned()
        .with_context(|| format!("{flag} requires a value"))
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct FileAccumulator {
    path: String,
    status: FileStatus,
    additions: u64,
    deletions: u64,
}

impl FileAccumulator {
    fn new(path: String) -> Self {
        Self {
            path,
            status: FileStatus::Modified,
            additions: 0,
            deletions: 0,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn local_review_parses_modified_added_deleted_and_renamed_files() {
        let files = changed_files_from_git_diff(
            "diff --git a/src/lib.rs b/src/lib.rs\n--- a/src/lib.rs\n+++ b/src/lib.rs\n@@ -1 +1,2 @@\n-old\n+new\n+line\n\
diff --git a/src/new.rs b/src/new.rs\nnew file mode 100644\n--- /dev/null\n+++ b/src/new.rs\n@@ -0,0 +1 @@\n+new\n\
diff --git a/src/old.rs b/src/old.rs\ndeleted file mode 100644\n--- a/src/old.rs\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n\
diff --git a/src/before.rs b/src/after.rs\nsimilarity index 100%\nrename from src/before.rs\nrename to src/after.rs\n",
        )
        .expect("diff parses");

        assert_eq!(files.len(), 4);
        assert_eq!(files[0].path, "src/lib.rs");
        assert_eq!(files[0].status, FileStatus::Modified);
        assert_eq!(files[0].additions, 2);
        assert_eq!(files[0].deletions, 1);
        assert_eq!(files[1].status, FileStatus::Added);
        assert_eq!(files[2].status, FileStatus::Deleted);
        assert_eq!(files[3].path, "src/after.rs");
        assert_eq!(files[3].status, FileStatus::Renamed);
    }

    #[test]
    fn local_review_rejects_malformed_and_duplicate_diffs() {
        assert!(changed_files_from_git_diff("").is_err());
        assert!(changed_files_from_git_diff("+line without header\n").is_err());
        assert!(
            changed_files_from_git_diff("diff --git a/src/lib.rs b/src/lib.rs extra\n")
                .expect_err("unsupported whitespace rejects")
                .to_string()
                .contains("unsupported whitespace")
        );
        assert!(changed_files_from_git_diff(
            "diff --git a/src/lib.rs b/src/lib.rs\n+one\n\
diff --git a/src/lib.rs b/src/lib.rs\n+two\n",
        )
        .expect_err("duplicate files reject")
        .to_string()
        .contains("duplicate file path"));
    }

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
