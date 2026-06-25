use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::process::Command;

use anyhow::{anyhow, bail, Context, Result};
use serde::Deserialize;
use serde_json::json;

use crate::digest::sha256_digest;
use crate::schema::{
    Change, ChangedFile, Diff, FileStatus, RequestContext, ReviewPolicy, ReviewRequest,
    RuntimeTarget, Source, SourceKind, WorkspaceContext, WorkspaceKind, WorkspaceRef,
    REVIEW_REQUEST_SCHEMA,
};

#[derive(Debug, Clone)]
pub struct RequestOptions {
    pub request_id: Option<String>,
    pub instructions: Vec<String>,
    pub local_runtime: Vec<RuntimeTarget>,
    pub allow_local_runtime: bool,
    pub allowed_env: Vec<String>,
    pub timeout_ms: u64,
}

#[derive(Debug, Clone)]
pub struct GitRangeRequestOptions {
    pub repo_path: PathBuf,
    pub base: String,
    pub head: String,
    pub base_workspace: Option<PathBuf>,
    pub title: Option<String>,
    pub description: Option<String>,
    pub repo: Option<String>,
    pub common: RequestOptions,
}

#[derive(Debug, Clone)]
pub struct PullRequestOptions {
    pub number: u64,
    pub repo: Option<String>,
    pub gh_binary: String,
    pub head_workspace: Option<PathBuf>,
    pub base_workspace: Option<PathBuf>,
    pub common: RequestOptions,
}

pub fn build_git_range_request(options: &GitRangeRequestOptions) -> Result<ReviewRequest> {
    let repo_path = absolute_path(&options.repo_path)?;
    let range = format!("{}...{}", options.base, options.head);
    let diff = run(
        &repo_path,
        "git",
        &[
            "diff",
            "--no-ext-diff",
            "--binary",
            "--find-renames",
            &range,
        ],
    )
    .with_context(|| format!("read git diff for {range}"))?;
    if diff.trim().is_empty() {
        bail!("git range {range} produced an empty diff");
    }

    let name_status = run(
        &repo_path,
        "git",
        &["diff", "--name-status", "--find-renames", &range],
    )
    .with_context(|| format!("read git changed files for {range}"))?;
    let numstat = run(
        &repo_path,
        "git",
        &["diff", "--numstat", "--find-renames", &range],
    )
    .with_context(|| format!("read git numstat for {range}"))?;
    let mut files = parse_name_status(&name_status)?;
    apply_numstat(&mut files, &parse_numstat(&numstat));

    let base_sha = git_output(&repo_path, &["rev-parse", &options.base])
        .with_context(|| format!("resolve base ref {}", options.base))?;
    let head_sha = git_output(&repo_path, &["rev-parse", &options.head])
        .with_context(|| format!("resolve head ref {}", options.head))?;
    let base_workspace = options
        .base_workspace
        .as_ref()
        .map(|path| absolute_path(path))
        .transpose()?;
    if let Some(path) = &base_workspace {
        validate_workspace("base", path, &base_sha)?;
    }
    let base_source = base_workspace.as_deref().unwrap_or(repo_path.as_path());
    let repo = options
        .repo
        .clone()
        .or_else(|| detect_repo_slug(&repo_path).ok());
    let title = options
        .title
        .clone()
        .unwrap_or_else(|| format!("Review {}...{}", options.base, options.head));
    let description = options
        .description
        .clone()
        .or_else(|| Some(format!("Generated from local git range `{range}`.")));
    let request_id = options.common.request_id.clone().unwrap_or_else(|| {
        format!(
            "git-range-{}-{}",
            sanitize_id(&options.base),
            short_sha(&head_sha)
        )
    });

    Ok(ReviewRequest {
        schema_version: REVIEW_REQUEST_SCHEMA.to_string(),
        request_id,
        source: Source {
            kind: SourceKind::GitRange,
            external_id: Some(range),
            repo: repo.clone(),
            uri: None,
            metadata: json!({
                "repo_path": repo_path,
            }),
        },
        change: Change {
            title,
            description,
            base_ref: Some(options.base.clone()),
            head_ref: Some(options.head.clone()),
            head_sha: Some(head_sha.clone()),
            diff: Diff {
                format: "unified".to_string(),
                digest: Some(sha256_digest(diff.as_bytes())),
                body: diff,
            },
            files,
        },
        context: RequestContext {
            summary: Some(
                "Generated from a local git range with head and base checkout access.".to_string(),
            ),
            acceptance: Vec::new(),
            instructions: options.common.instructions.clone(),
            artifacts: Vec::new(),
            workspaces: WorkspaceContext {
                head: Some(WorkspaceRef {
                    kind: WorkspaceKind::Checkout,
                    path: repo_path.display().to_string(),
                    ref_name: Some(options.head.clone()),
                    sha: Some(head_sha),
                }),
                base: Some(WorkspaceRef {
                    kind: WorkspaceKind::Checkout,
                    path: base_source.display().to_string(),
                    ref_name: Some(options.base.clone()),
                    sha: Some(base_sha),
                }),
            },
            local_runtime: options.common.local_runtime.clone(),
            remote_runtime: Vec::new(),
            metadata: json!({}),
        },
        policy: policy_from_options(&options.common),
    })
}

pub fn build_pull_request(options: &PullRequestOptions) -> Result<ReviewRequest> {
    let pr = gh_pr_view(
        options.number,
        options.repo.as_deref(),
        options.gh_binary.as_str(),
    )?;
    let diff = gh_pr_diff(
        options.number,
        options.repo.as_deref(),
        options.gh_binary.as_str(),
    )?;
    if diff.trim().is_empty() {
        bail!("pull request #{} produced an empty diff", options.number);
    }
    let head_workspace = options
        .head_workspace
        .as_ref()
        .map(|path| absolute_path(path))
        .transpose()?;
    let base_workspace = options
        .base_workspace
        .as_ref()
        .map(|path| absolute_path(path))
        .transpose()?;
    if base_workspace.is_some() && head_workspace.is_none() {
        bail!("--base-workspace requires --head-workspace for PR requests");
    }
    let head_sha = require_pr_head_sha(options.number, &pr)?;
    let base_sha = if base_workspace.is_some() {
        Some(require_pr_base_sha(options.number, &pr)?)
    } else {
        None
    };
    let repo_detection_path = head_workspace.as_deref().unwrap_or_else(|| Path::new("."));
    let repo = options
        .repo
        .clone()
        .or_else(|| detect_repo_slug(repo_detection_path).ok());
    let request_id = options
        .common
        .request_id
        .clone()
        .unwrap_or_else(|| format!("github-pr-{}-{}", options.number, short_sha(&head_sha)));
    if let Some(path) = &head_workspace {
        validate_workspace("head", path, &head_sha)?;
    }
    if let (Some(path), Some(base_sha)) = (&base_workspace, &base_sha) {
        validate_workspace("base", path, base_sha)?;
    }

    Ok(ReviewRequest {
        schema_version: REVIEW_REQUEST_SCHEMA.to_string(),
        request_id,
        source: Source {
            kind: SourceKind::GithubPr,
            external_id: Some(format!("#{}", options.number)),
            repo,
            uri: pr.url.clone(),
            metadata: json!({
                "number": pr.number,
                "url": pr.url,
            }),
        },
        change: Change {
            title: pr.title,
            description: pr.body,
            base_ref: pr.base_ref_name.clone(),
            head_ref: pr.head_ref_name.clone(),
            head_sha: Some(head_sha.clone()),
            diff: Diff {
                format: "unified".to_string(),
                digest: Some(sha256_digest(diff.as_bytes())),
                body: diff,
            },
            files: pr.files.into_iter().map(ChangedFile::from).collect(),
        },
        context: RequestContext {
            summary: Some(format!(
                "Generated from GitHub pull request #{}.",
                options.number
            )),
            acceptance: Vec::new(),
            instructions: options.common.instructions.clone(),
            artifacts: Vec::new(),
            workspaces: WorkspaceContext {
                head: head_workspace.map(|path| WorkspaceRef {
                    kind: WorkspaceKind::Checkout,
                    path: path.display().to_string(),
                    ref_name: pr.head_ref_name,
                    sha: Some(head_sha),
                }),
                base: base_workspace.map(|path| WorkspaceRef {
                    kind: WorkspaceKind::Checkout,
                    path: path.display().to_string(),
                    ref_name: pr.base_ref_name,
                    sha: base_sha,
                }),
            },
            local_runtime: options.common.local_runtime.clone(),
            remote_runtime: Vec::new(),
            metadata: json!({}),
        },
        policy: policy_from_options(&options.common),
    })
}

pub fn fetch_pull_request_head_sha(
    number: u64,
    repo: Option<&str>,
    gh_binary: &str,
) -> Result<String> {
    let pr = gh_pr_view(number, repo, gh_binary)?;
    require_pr_head_sha(number, &pr)
}

fn policy_from_options(options: &RequestOptions) -> ReviewPolicy {
    ReviewPolicy {
        timeout_ms: options.timeout_ms,
        allow_local_runtime: options.allow_local_runtime,
        allowed_env: options.allowed_env.clone(),
        ..ReviewPolicy::default()
    }
}

fn run(cwd: &Path, program: &str, args: &[&str]) -> Result<String> {
    let output = Command::new(program)
        .args(args)
        .current_dir(cwd)
        .output()
        .with_context(|| format!("run {program} {}", args.join(" ")))?;
    if !output.status.success() {
        bail!(
            "{program} {} failed: {}",
            args.join(" "),
            String::from_utf8_lossy(&output.stderr)
        );
    }
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

fn git_output(cwd: &Path, args: &[&str]) -> Result<String> {
    Ok(run(cwd, "git", args)?.trim().to_string())
}

fn absolute_path(path: &Path) -> Result<PathBuf> {
    if path.is_absolute() {
        Ok(path.to_path_buf())
    } else {
        std::env::current_dir()
            .context("read current directory")
            .map(|cwd| cwd.join(path))
    }
}

fn require_pr_head_sha(number: u64, pr: &GhPullRequest) -> Result<String> {
    pr.head_ref_oid
        .as_ref()
        .filter(|sha| !sha.trim().is_empty())
        .cloned()
        .ok_or_else(|| anyhow!("pull request #{number} is missing headRefOid"))
}

fn require_pr_base_sha(number: u64, pr: &GhPullRequest) -> Result<String> {
    pr.base_ref_oid
        .as_ref()
        .filter(|sha| !sha.trim().is_empty())
        .cloned()
        .ok_or_else(|| anyhow!("pull request #{number} is missing baseRefOid"))
}

fn validate_workspace(label: &str, path: &Path, expected_sha: &str) -> Result<()> {
    let dirty = git_output(path, &["status", "--porcelain", "--untracked-files=no"])
        .with_context(|| format!("inspect {label} workspace {}", path.display()))?;
    if !dirty.trim().is_empty() {
        bail!(
            "{label} workspace {} has uncommitted tracked changes; commit, stash, or omit --{label}-workspace",
            path.display()
        );
    }

    let actual = git_output(path, &["rev-parse", "HEAD"])
        .with_context(|| format!("resolve {label} workspace {}", path.display()))?;
    if actual != expected_sha {
        bail!(
            "{label} workspace {} is at {actual}, but expected sha is {expected_sha}",
            path.display()
        );
    }
    Ok(())
}

fn detect_repo_slug(repo_path: &Path) -> Result<String> {
    let remote = git_output(repo_path, &["config", "--get", "remote.origin.url"])?;
    parse_github_slug(&remote).ok_or_else(|| anyhow!("remote origin is not a GitHub slug"))
}

fn parse_github_slug(remote: &str) -> Option<String> {
    let mut value = remote.trim().trim_end_matches(".git").to_string();
    if let Some(rest) = value.strip_prefix("git@github.com:") {
        value = rest.to_string();
    } else if let Some(rest) = value.strip_prefix("https://github.com/") {
        value = rest.to_string();
    } else if let Some(rest) = value.strip_prefix("ssh://git@github.com/") {
        value = rest.to_string();
    }
    let parts: Vec<&str> = value.split('/').collect();
    if parts.len() == 2 && !parts[0].is_empty() && !parts[1].is_empty() {
        Some(value)
    } else {
        None
    }
}

fn parse_name_status(raw: &str) -> Result<Vec<ChangedFile>> {
    raw.lines()
        .filter(|line| !line.trim().is_empty())
        .map(parse_name_status_line)
        .collect()
}

fn parse_name_status_line(line: &str) -> Result<ChangedFile> {
    let parts: Vec<&str> = line.split('\t').collect();
    let status = parts
        .first()
        .ok_or_else(|| anyhow!("missing status in name-status line {line:?}"))?;
    let code = status
        .chars()
        .next()
        .ok_or_else(|| anyhow!("empty status in name-status line {line:?}"))?;
    match code {
        'A' => changed_file(parts.get(1), FileStatus::Added, None),
        'M' | 'T' => changed_file(parts.get(1), FileStatus::Modified, None),
        'D' => changed_file(parts.get(1), FileStatus::Removed, None),
        'R' => changed_file(parts.get(2), FileStatus::Renamed, parts.get(1).copied()),
        'C' => changed_file(parts.get(2), FileStatus::Copied, parts.get(1).copied()),
        other => Err(anyhow!(
            "unsupported git change status {other:?} in {line:?}"
        )),
    }
}

fn changed_file(
    path: Option<&&str>,
    status: FileStatus,
    old_path: Option<&str>,
) -> Result<ChangedFile> {
    let path = path
        .copied()
        .ok_or_else(|| anyhow!("missing path for changed file"))?;
    Ok(ChangedFile {
        path: path.to_string(),
        status,
        old_path: old_path.map(str::to_string),
        additions: None,
        deletions: None,
    })
}

fn parse_numstat(raw: &str) -> BTreeMap<String, (Option<u32>, Option<u32>)> {
    raw.lines()
        .filter_map(|line| {
            let parts: Vec<&str> = line.split('\t').collect();
            if parts.len() < 3 {
                return None;
            }
            let path = parse_numstat_path(parts.last()?);
            let additions = parts[0].parse::<u32>().ok();
            let deletions = parts[1].parse::<u32>().ok();
            Some((path, (additions, deletions)))
        })
        .collect()
}

fn parse_numstat_path(path: &str) -> String {
    if let (Some(open), Some(close)) = (path.find('{'), path.rfind('}')) {
        if open < close {
            let prefix = &path[..open];
            let middle = &path[open + 1..close];
            let suffix = &path[close + 1..];
            if let Some((_, new_path)) = middle.split_once(" => ") {
                return format!("{prefix}{new_path}{suffix}");
            }
        }
    }
    if let Some((_, new_path)) = path.split_once(" => ") {
        return new_path.to_string();
    }
    path.to_string()
}

fn apply_numstat(files: &mut [ChangedFile], stats: &BTreeMap<String, (Option<u32>, Option<u32>)>) {
    for file in files {
        if let Some((additions, deletions)) = stats.get(&file.path) {
            file.additions = *additions;
            file.deletions = *deletions;
        }
    }
}

fn sanitize_id(value: &str) -> String {
    value
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || ch == '-' || ch == '_' {
                ch
            } else {
                '-'
            }
        })
        .collect()
}

fn short_sha(value: &str) -> String {
    value.chars().take(12).collect()
}

fn gh_pr_view(number: u64, repo: Option<&str>, gh_binary: &str) -> Result<GhPullRequest> {
    let number = number.to_string();
    let fields = "number,title,body,url,baseRefName,baseRefOid,headRefName,headRefOid,files";
    let mut args = vec!["pr", "view", number.as_str(), "--json", fields];
    if let Some(repo) = repo {
        args.extend(["-R", repo]);
    }
    let output = run(Path::new("."), gh_binary, &args)?;
    serde_json::from_str(&output).context("parse gh pr view JSON")
}

fn gh_pr_diff(number: u64, repo: Option<&str>, gh_binary: &str) -> Result<String> {
    let number = number.to_string();
    let mut args = vec!["pr", "diff", number.as_str(), "--patch", "--color", "never"];
    if let Some(repo) = repo {
        args.extend(["-R", repo]);
    }
    run(Path::new("."), gh_binary, &args)
}

#[derive(Debug, Deserialize)]
struct GhPullRequest {
    number: u64,
    title: String,
    body: Option<String>,
    url: Option<String>,
    #[serde(rename = "baseRefName")]
    base_ref_name: Option<String>,
    #[serde(rename = "baseRefOid")]
    base_ref_oid: Option<String>,
    #[serde(rename = "headRefName")]
    head_ref_name: Option<String>,
    #[serde(rename = "headRefOid")]
    head_ref_oid: Option<String>,
    #[serde(default)]
    files: Vec<GhPrFile>,
}

#[derive(Debug, Deserialize)]
struct GhPrFile {
    path: String,
    #[serde(default, rename = "changeType")]
    change_type: Option<String>,
    additions: Option<u32>,
    deletions: Option<u32>,
}

impl From<GhPrFile> for ChangedFile {
    fn from(file: GhPrFile) -> Self {
        let status = match file.change_type.as_deref() {
            Some("ADDED") => FileStatus::Added,
            Some("DELETED") => FileStatus::Removed,
            Some("RENAMED") => FileStatus::Renamed,
            Some("COPIED") => FileStatus::Copied,
            _ => FileStatus::Modified,
        };
        Self {
            path: file.path,
            status,
            old_path: None,
            additions: file.additions,
            deletions: file.deletions,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn init_repo() -> tempfile::TempDir {
        let repo = tempfile::tempdir().unwrap();
        run(repo.path(), "git", &["init", "-q"]).unwrap();
        run(
            repo.path(),
            "git",
            &["config", "user.email", "cerberus@example.invalid"],
        )
        .unwrap();
        run(
            repo.path(),
            "git",
            &["config", "user.name", "Cerberus Test"],
        )
        .unwrap();
        repo
    }

    fn commit_file(repo: &Path, contents: &str, message: &str) -> String {
        fs::write(repo.join("file.txt"), contents).unwrap();
        run(repo, "git", &["add", "file.txt"]).unwrap();
        run(repo, "git", &["commit", "-q", "-m", message]).unwrap();
        git_output(repo, &["rev-parse", "HEAD"]).unwrap()
    }

    fn gh_pr(head_ref_oid: Option<String>) -> GhPullRequest {
        GhPullRequest {
            number: 7,
            title: "title".to_string(),
            body: None,
            url: None,
            base_ref_name: Some("master".to_string()),
            base_ref_oid: Some("def456".to_string()),
            head_ref_name: Some("branch".to_string()),
            head_ref_oid,
            files: Vec::new(),
        }
    }

    #[test]
    fn parses_name_status_with_rename_and_type_change() {
        let files =
            parse_name_status("M\tsrc/lib.rs\nR100\told.rs\tnew.rs\nT\tscript.sh\n").unwrap();
        assert_eq!(files.len(), 3);
        assert_eq!(files[0].status, FileStatus::Modified);
        assert_eq!(files[0].path, "src/lib.rs");
        assert_eq!(files[1].status, FileStatus::Renamed);
        assert_eq!(files[1].old_path.as_deref(), Some("old.rs"));
        assert_eq!(files[1].path, "new.rs");
        assert_eq!(files[2].status, FileStatus::Modified);
        assert_eq!(files[2].path, "script.sh");
    }

    #[test]
    fn parses_numstat_rename_paths_to_new_path() {
        let stats = parse_numstat("2\t1\tsrc/{old.rs => new.rs}\n3\t0\told.txt => new.txt\n");
        assert_eq!(stats.get("src/new.rs"), Some(&(Some(2), Some(1))));
        assert_eq!(stats.get("new.txt"), Some(&(Some(3), Some(0))));
    }

    #[test]
    fn parses_github_remote_slugs() {
        assert_eq!(
            parse_github_slug("https://github.com/misty-step/cerberus.git"),
            Some("misty-step/cerberus".to_string())
        );
        assert_eq!(
            parse_github_slug("git@github.com:misty-step/cerberus.git"),
            Some("misty-step/cerberus".to_string())
        );
    }

    #[test]
    fn treats_missing_github_file_change_type_as_modified() {
        let pr: GhPullRequest = serde_json::from_str(
            r#"{
                "number": 7,
                "title": "title",
                "body": null,
                "url": "https://github.com/example/fixture/pull/7",
                "baseRefName": "main",
                "baseRefOid": "def456",
                "headRefName": "branch",
                "headRefOid": "abc123",
                "files": [
                    {
                        "path": "src/lib.rs",
                        "additions": 3,
                        "deletions": 1
                    }
                ]
            }"#,
        )
        .unwrap();

        let file = ChangedFile::from(pr.files.into_iter().next().unwrap());
        assert_eq!(file.path, "src/lib.rs");
        assert_eq!(file.status, FileStatus::Modified);
        assert_eq!(file.additions, Some(3));
        assert_eq!(file.deletions, Some(1));
    }

    #[test]
    fn validates_clean_matching_head_workspace() {
        let repo = init_repo();
        let head = commit_file(repo.path(), "one\n", "one");
        validate_workspace("head", repo.path(), &head).unwrap();
    }

    #[test]
    fn rejects_mismatched_head_workspace_sha() {
        let repo = init_repo();
        let old = commit_file(repo.path(), "one\n", "one");
        let _new = commit_file(repo.path(), "two\n", "two");
        let err = validate_workspace("head", repo.path(), &old).unwrap_err();
        assert!(err.to_string().contains("expected sha is"));
    }

    #[test]
    fn rejects_dirty_head_workspace() {
        let repo = init_repo();
        let head = commit_file(repo.path(), "one\n", "one");
        fs::write(repo.path().join("file.txt"), "dirty\n").unwrap();
        let err = validate_workspace("head", repo.path(), &head).unwrap_err();
        assert!(err.to_string().contains("uncommitted tracked changes"));
    }

    #[test]
    fn rejects_github_pr_without_head_oid() {
        let err = require_pr_head_sha(7, &gh_pr(None)).unwrap_err();
        assert!(err.to_string().contains("missing headRefOid"));
    }

    #[test]
    fn requires_non_empty_github_pr_head_oid() {
        let err = require_pr_head_sha(7, &gh_pr(Some("".to_string()))).unwrap_err();
        assert!(err.to_string().contains("missing headRefOid"));
        assert_eq!(
            require_pr_head_sha(7, &gh_pr(Some("abc123".to_string()))).unwrap(),
            "abc123"
        );
    }

    #[test]
    fn requires_non_empty_github_pr_base_oid_when_requested() {
        let mut pr = gh_pr(Some("abc123".to_string()));
        assert_eq!(require_pr_base_sha(7, &pr).unwrap(), "def456");
        pr.base_ref_oid = Some("".to_string());
        let err = require_pr_base_sha(7, &pr).unwrap_err();
        assert!(err.to_string().contains("missing baseRefOid"));
    }
}
