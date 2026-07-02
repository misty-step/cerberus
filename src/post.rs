use std::collections::{BTreeMap, BTreeSet};
use std::io::Write;
use std::process::{Command, Stdio};

use anyhow::{anyhow, bail, Context, Result};
use clap::ValueEnum;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::digest::sha256_digest;
use crate::render::render_markdown;
use crate::schema::{
    AnchorKind, Comment, CommentKind, LifecycleState, ReviewArtifact, ReviewRequest, Verdict,
};
use crate::secrets::redact_secret;

pub const POST_PLAN_SCHEMA: &str = "cerberus.post_plan.v1";
pub const POST_RESULT_SCHEMA: &str = "cerberus.post_result.v1";

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, ValueEnum)]
#[serde(rename_all = "snake_case")]
pub enum SummaryTarget {
    CheckRun,
    Status,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ExistingGithubState {
    pub summary_comment_id: Option<u64>,
    pub inline_comment_ids: BTreeMap<String, u64>,
    pub check_run_id: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PostPlan {
    pub schema_version: String,
    pub repo: String,
    pub pull_request: u64,
    pub head_sha: String,
    pub artifact_id: String,
    pub artifact_digest: String,
    pub summary_target: SummaryTarget,
    pub operations: Vec<PlannedOperation>,
    pub unmapped_comments: Vec<UnmappedComment>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PlannedOperation {
    pub id: String,
    pub method: String,
    pub path: String,
    pub description: String,
    pub idempotency_key: String,
    pub body: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct UnmappedComment {
    pub comment_id: String,
    pub reason: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PostResult {
    pub schema_version: String,
    pub plan_digest: String,
    pub applied: Vec<AppliedOperation>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AppliedOperation {
    pub operation_id: String,
    pub method: String,
    pub path: String,
    pub response: Value,
}

pub fn trusted_lifecycle(artifact: &ReviewArtifact) -> bool {
    matches!(
        artifact.lifecycle_state,
        LifecycleState::Completed | LifecycleState::CompletedDegraded
    )
}

pub fn build_post_plan(
    request: &ReviewRequest,
    artifact: &ReviewArtifact,
    repo: &str,
    pull_request: u64,
    summary_target: SummaryTarget,
    existing: &ExistingGithubState,
) -> Result<PostPlan> {
    let head_sha = request
        .change
        .head_sha
        .clone()
        .ok_or_else(|| anyhow!("review-pr requires request.change.head_sha"))?;
    let artifact_digest = sha256_digest(serde_json::to_vec(artifact)?);
    let changed_lines = changed_new_lines_by_path(&request.change.diff.body)?;
    let summary_marker = summary_marker(repo, pull_request, &head_sha);
    let mut operations = Vec::new();
    let mut unmapped_comments = Vec::new();
    let mut new_inline_comments = Vec::new();

    operations.push(summary_operation(SummaryOperationInput {
        artifact,
        repo,
        pull_request,
        head_sha: &head_sha,
        artifact_digest: &artifact_digest,
        target: summary_target,
        check_run_id: existing.check_run_id,
        target_url: request.source.uri.as_deref(),
    }));

    for comment in &artifact.comments {
        if let Some(inline) = inline_comment_body(comment, &head_sha, &changed_lines) {
            let marker_key = inline.marker_key.clone();
            if let Some(comment_id) = existing.inline_comment_ids.get(&marker_key) {
                operations.push(PlannedOperation {
                    id: format!("update-inline-{marker_key}"),
                    method: "PATCH".to_string(),
                    path: format!("/repos/{repo}/pulls/comments/{comment_id}"),
                    description: format!("Update Cerberus inline comment {}", comment.id),
                    idempotency_key: marker_key,
                    body: json!({ "body": inline.body }),
                });
            } else {
                new_inline_comments.push(json!({
                    "path": inline.path,
                    "line": inline.line,
                    "side": "RIGHT",
                    "body": inline.body,
                }));
            }
        } else {
            unmapped_comments.push(UnmappedComment {
                comment_id: comment.id.clone(),
                reason: unmapped_reason(comment, &changed_lines),
            });
        }
    }

    let summary_body = summary_body(artifact, &summary_marker, &unmapped_comments);
    if let Some(comment_id) = existing.summary_comment_id {
        operations.push(PlannedOperation {
            id: "update-summary-comment".to_string(),
            method: "PATCH".to_string(),
            path: format!("/repos/{repo}/issues/comments/{comment_id}"),
            description: "Update Cerberus PR summary comment".to_string(),
            idempotency_key: summary_marker.clone(),
            body: json!({ "body": summary_body }),
        });
    } else {
        operations.push(PlannedOperation {
            id: "create-summary-comment".to_string(),
            method: "POST".to_string(),
            path: format!("/repos/{repo}/issues/{pull_request}/comments"),
            description: "Create Cerberus PR summary comment".to_string(),
            idempotency_key: summary_marker,
            body: json!({ "body": summary_body }),
        });
    }

    if !new_inline_comments.is_empty() {
        operations.push(PlannedOperation {
            id: "create-inline-review".to_string(),
            method: "POST".to_string(),
            path: format!("/repos/{repo}/pulls/{pull_request}/reviews"),
            description: "Create Cerberus PR review with new inline comments".to_string(),
            idempotency_key: format!("cerberus:inline-review:{repo}:{pull_request}:{head_sha}"),
            body: json!({
                "event": "COMMENT",
                "body": format!("Cerberus inline review comments for head `{}`.", head_sha),
                "commit_id": head_sha,
                "comments": new_inline_comments,
            }),
        });
    }

    Ok(PostPlan {
        schema_version: POST_PLAN_SCHEMA.to_string(),
        repo: repo.to_string(),
        pull_request,
        head_sha,
        artifact_id: artifact.artifact_id.clone(),
        artifact_digest,
        summary_target,
        operations,
        unmapped_comments,
    })
}

pub fn changed_new_lines_by_path(diff: &str) -> Result<BTreeMap<String, BTreeSet<u32>>> {
    let mut changed = BTreeMap::<String, BTreeSet<u32>>::new();
    let mut current_path: Option<String> = None;
    let mut new_line: Option<u32> = None;

    for line in diff.lines() {
        if let Some(path) = line.strip_prefix("+++ b/") {
            current_path = Some(path.to_string());
            changed.entry(path.to_string()).or_default();
            new_line = None;
            continue;
        }
        if line.starts_with("+++ /dev/null") {
            current_path = None;
            new_line = None;
            continue;
        }
        if line.starts_with("@@ ") {
            new_line = Some(parse_hunk_new_start(line)?);
            continue;
        }
        let Some(path) = current_path.as_ref() else {
            continue;
        };
        let Some(line_no) = new_line else {
            continue;
        };
        if line.starts_with('+') && !line.starts_with("+++") {
            changed.entry(path.clone()).or_default().insert(line_no);
            new_line = Some(line_no + 1);
        } else if (line.starts_with('-') && !line.starts_with("---")) || line.starts_with('\\') {
            continue;
        } else {
            new_line = Some(line_no + 1);
        }
    }

    Ok(changed)
}

fn parse_hunk_new_start(line: &str) -> Result<u32> {
    let marker = line
        .split_whitespace()
        .find(|part| part.starts_with('+'))
        .ok_or_else(|| anyhow!("hunk header missing new range: {line}"))?;
    let start = marker
        .trim_start_matches('+')
        .split(',')
        .next()
        .ok_or_else(|| anyhow!("hunk header missing new start: {line}"))?;
    start
        .parse::<u32>()
        .with_context(|| format!("parse hunk new start from {line:?}"))
}

struct SummaryOperationInput<'a> {
    artifact: &'a ReviewArtifact,
    repo: &'a str,
    pull_request: u64,
    head_sha: &'a str,
    artifact_digest: &'a str,
    target: SummaryTarget,
    check_run_id: Option<u64>,
    target_url: Option<&'a str>,
}

fn summary_operation(input: SummaryOperationInput<'_>) -> PlannedOperation {
    match input.target {
        SummaryTarget::CheckRun => {
            let body = check_run_body(
                input.artifact,
                input.pull_request,
                input.head_sha,
                input.artifact_digest,
                false,
            );
            if let Some(check_run_id) = input.check_run_id {
                PlannedOperation {
                    id: "update-check-run".to_string(),
                    method: "PATCH".to_string(),
                    path: format!("/repos/{}/check-runs/{check_run_id}", input.repo),
                    description: "Update Cerberus check run for this PR head".to_string(),
                    idempotency_key: format!(
                        "cerberus:check-run:{}:{}:{}",
                        input.repo, input.pull_request, input.head_sha
                    ),
                    body,
                }
            } else {
                let body = check_run_body(
                    input.artifact,
                    input.pull_request,
                    input.head_sha,
                    input.artifact_digest,
                    true,
                );
                PlannedOperation {
                    id: "create-check-run".to_string(),
                    method: "POST".to_string(),
                    path: format!("/repos/{}/check-runs", input.repo),
                    description: "Create Cerberus check run for this PR head".to_string(),
                    idempotency_key: format!(
                        "cerberus:check-run:{}:{}:{}",
                        input.repo, input.pull_request, input.head_sha
                    ),
                    body,
                }
            }
        }
        SummaryTarget::Status => PlannedOperation {
            id: "create-commit-status".to_string(),
            method: "POST".to_string(),
            path: format!("/repos/{}/statuses/{}", input.repo, input.head_sha),
            description: "Create Cerberus commit status for this PR head".to_string(),
            idempotency_key: format!(
                "cerberus:status:{}:{}:{}",
                input.repo, input.pull_request, input.head_sha
            ),
            body: json!({
                "state": status_state(&input.artifact.verdict),
                "target_url": input.target_url,
                "description": format!("Cerberus Review: {}", input.artifact.verdict.label()),
                "context": "Cerberus Review",
            }),
        },
    }
}

fn check_run_body(
    artifact: &ReviewArtifact,
    pull_request: u64,
    head_sha: &str,
    artifact_digest: &str,
    include_head_sha: bool,
) -> Value {
    let mut body = json!({
        "name": "Cerberus Review",
        "status": "completed",
        "conclusion": check_conclusion(&artifact.verdict),
        "external_id": format!("cerberus:pr:{pull_request}:{head_sha}"),
        "output": {
            "title": format!("Cerberus Review: {}", artifact.verdict.label()),
            "summary": format!(
                "{}\n\nArtifact: `{}`\nDigest: `{}`",
                artifact.summary.body,
                artifact.artifact_id,
                artifact_digest
            ),
        },
    });
    if include_head_sha {
        body["head_sha"] = json!(head_sha);
    }
    body
}

fn inline_comment_body(
    comment: &Comment,
    head_sha: &str,
    changed_lines: &BTreeMap<String, BTreeSet<u32>>,
) -> Option<InlineCommentBody> {
    if comment.kind != CommentKind::Inline || comment.anchor.kind != AnchorKind::Inline {
        return None;
    }
    let path = comment.anchor.path.as_ref()?;
    let line = comment.anchor.line?;
    if !changed_lines
        .get(path)
        .map(|lines| lines.contains(&line))
        .unwrap_or(false)
    {
        return None;
    }
    let marker_key = inline_marker_key(comment);
    let marker = inline_marker(head_sha, &marker_key);
    Some(InlineCommentBody {
        path: path.clone(),
        line,
        marker_key,
        body: format!("{}\n\n{}", comment.body.trim(), marker),
    })
}

fn unmapped_reason(comment: &Comment, changed_lines: &BTreeMap<String, BTreeSet<u32>>) -> String {
    if comment.kind != CommentKind::Inline || comment.anchor.kind != AnchorKind::Inline {
        return "comment is contextual or not anchored inline".to_string();
    }
    let Some(path) = &comment.anchor.path else {
        return "inline comment is missing a path".to_string();
    };
    let Some(line) = comment.anchor.line else {
        return "inline comment is missing a line".to_string();
    };
    if !changed_lines.contains_key(path) {
        return format!("path {path} is not present in the PR diff");
    }
    format!("line {line} in {path} is not a changed new-side PR line")
}

fn summary_body(
    artifact: &ReviewArtifact,
    marker: &str,
    unmapped_comments: &[UnmappedComment],
) -> String {
    let mut body = render_markdown(artifact);
    if !unmapped_comments.is_empty() {
        body.push_str("\n\n## Contextual Comment Fallbacks\n\n");
        for comment in unmapped_comments {
            body.push_str(&format!("- `{}`: {}\n", comment.comment_id, comment.reason));
        }
    }
    body.push_str("\n\n");
    body.push_str(marker);
    body
}

fn summary_marker(repo: &str, pull_request: u64, head_sha: &str) -> String {
    format!("<!-- cerberus:review-pr:v1 repo={repo} pr={pull_request} head={head_sha} -->")
}

fn inline_marker(head_sha: &str, marker_key: &str) -> String {
    format!("<!-- cerberus:inline:v1 head={head_sha} key={marker_key} -->")
}

fn inline_marker_key(comment: &Comment) -> String {
    comment
        .dedupe_key
        .as_ref()
        .filter(|key| !key.trim().is_empty())
        .cloned()
        .unwrap_or_else(|| comment.id.clone())
}

fn extract_inline_marker_key(body: &str, head_sha: &str) -> Option<String> {
    let prefix = format!("<!-- cerberus:inline:v1 head={head_sha} key=");
    let start = body.find(&prefix)? + prefix.len();
    let rest = &body[start..];
    let end = rest.find(" -->")?;
    Some(rest[..end].to_string())
}

fn check_conclusion(verdict: &Verdict) -> &'static str {
    match verdict {
        Verdict::Pass => "success",
        Verdict::Warn => "neutral",
        Verdict::Fail => "failure",
        Verdict::Skip => "skipped",
    }
}

fn status_state(verdict: &Verdict) -> &'static str {
    match verdict {
        Verdict::Pass | Verdict::Warn | Verdict::Skip => "success",
        Verdict::Fail => "failure",
    }
}

#[derive(Debug, Clone)]
struct InlineCommentBody {
    path: String,
    line: u32,
    marker_key: String,
    body: String,
}

#[derive(Debug, Clone)]
pub struct GithubClient {
    binary: String,
    token: Option<String>,
}

impl GithubClient {
    pub fn new(binary: impl Into<String>) -> Self {
        Self {
            binary: binary.into(),
            token: None,
        }
    }

    pub fn with_token(mut self, token: impl Into<String>) -> Self {
        self.token = Some(token.into());
        self
    }

    pub fn binary(&self) -> &str {
        &self.binary
    }

    pub fn read_existing_state(
        &self,
        repo: &str,
        pull_request: u64,
        head_sha: &str,
        summary_target: SummaryTarget,
    ) -> Result<ExistingGithubState> {
        let summary_marker = summary_marker(repo, pull_request, head_sha);
        let issue_comments =
            self.list_comments_paginated(&format!("/repos/{repo}/issues/{pull_request}/comments"))?;
        let summary_comment_id = issue_comments
            .iter()
            .find(|comment| {
                comment
                    .body
                    .as_deref()
                    .map(|body| body.contains(&summary_marker))
                    .unwrap_or(false)
            })
            .map(|comment| comment.id);
        let mut state = ExistingGithubState {
            summary_comment_id,
            ..ExistingGithubState::default()
        };

        let review_comments =
            self.list_comments_paginated(&format!("/repos/{repo}/pulls/{pull_request}/comments"))?;
        for comment in review_comments {
            if let Some(body) = comment.body.as_deref() {
                if let Some(key) = extract_inline_marker_key(body, head_sha) {
                    state.inline_comment_ids.insert(key, comment.id);
                }
            }
        }

        if summary_target == SummaryTarget::CheckRun {
            let external_id = format!("cerberus:pr:{pull_request}:{head_sha}");
            state.check_run_id = self
                .list_check_runs(repo, head_sha)?
                .into_iter()
                .find(|run| run.external_id.as_deref() == Some(external_id.as_str()))
                .map(|run| run.id);
        }

        Ok(state)
    }

    fn list_comments_paginated(&self, path: &str) -> Result<Vec<GithubComment>> {
        let mut all = Vec::new();
        for page in 1.. {
            let comments: Vec<GithubComment> =
                self.api_json("GET", &format!("{path}?per_page=100&page={page}"), None)?;
            let done = comments.len() < 100;
            all.extend(comments);
            if done {
                break;
            }
        }
        Ok(all)
    }

    fn list_check_runs(&self, repo: &str, head_sha: &str) -> Result<Vec<CheckRun>> {
        let mut all = Vec::new();
        for page in 1.. {
            let runs: CheckRunList = self.api_json(
                "GET",
                &format!(
                    "/repos/{repo}/commits/{head_sha}/check-runs?check_name=Cerberus%20Review&per_page=100&page={page}"
                ),
                None,
            )?;
            let count = runs.check_runs.len();
            all.extend(runs.check_runs);
            if count < 100 {
                break;
            }
        }
        Ok(all)
    }

    pub fn apply_plan(&self, plan: &PostPlan) -> Result<PostResult> {
        let mut applied = Vec::new();
        for operation in &plan.operations {
            let response = self.api_json::<Value>(
                &operation.method,
                &operation.path,
                Some(operation.body.clone()),
            )?;
            applied.push(AppliedOperation {
                operation_id: operation.id.clone(),
                method: operation.method.clone(),
                path: operation.path.clone(),
                response,
            });
        }
        Ok(PostResult {
            schema_version: POST_RESULT_SCHEMA.to_string(),
            plan_digest: sha256_digest(serde_json::to_vec(plan)?),
            applied,
        })
    }

    fn api_json<T>(&self, method: &str, path: &str, body: Option<Value>) -> Result<T>
    where
        T: serde::de::DeserializeOwned,
    {
        let output = self.api_raw(method, path, body)?;
        serde_json::from_str(&output)
            .with_context(|| format!("parse gh api response for {method} {path}"))
    }

    fn api_raw(&self, method: &str, path: &str, body: Option<Value>) -> Result<String> {
        let mut command = Command::new(&self.binary);
        command.arg("api").arg("--method").arg(method).arg(path);
        if let Some(token) = &self.token {
            command
                .env("GH_TOKEN", token)
                .env_remove("GITHUB_TOKEN")
                .env_remove("GH_ENTERPRISE_TOKEN")
                .env_remove("GITHUB_ENTERPRISE_TOKEN");
        }
        if body.is_some() {
            command.arg("--input").arg("-");
            command.stdin(Stdio::piped());
        }
        command.stdout(Stdio::piped()).stderr(Stdio::piped());
        let mut child = command
            .spawn()
            .with_context(|| format!("run {} api --method {method} {path}", self.binary))?;
        if let Some(body) = body {
            let stdin = child
                .stdin
                .as_mut()
                .ok_or_else(|| anyhow!("open gh api stdin"))?;
            stdin.write_all(serde_json::to_string(&body)?.as_bytes())?;
        }
        let output = child
            .wait_with_output()
            .with_context(|| format!("wait for gh api --method {method} {path}"))?;
        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            let stderr = redact_secret(&stderr, self.token.as_deref());
            if path.contains("/check-runs") && stderr.contains("403") {
                bail!(
                    "{} api --method {method} {path} failed: {stderr}\n\n\
                     This token lacks Checks-write (a classic PAT without the `checks` scope, \
                     or a GitHub App install without Checks permission, commonly hits this). \
                     Retry with --summary-target status, which only needs Statuses-write.",
                    self.binary
                );
            }
            bail!(
                "{} api --method {method} {path} failed: {}",
                self.binary,
                stderr
            );
        }
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    }
}

#[derive(Debug, Deserialize)]
struct GithubComment {
    id: u64,
    body: Option<String>,
}

#[derive(Debug, Deserialize)]
struct CheckRunList {
    #[serde(default)]
    check_runs: Vec<CheckRun>,
}

#[derive(Debug, Deserialize)]
struct CheckRun {
    id: u64,
    #[serde(default)]
    external_id: Option<String>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::digest::request_digest;
    use crate::schema::{
        Anchor, AnchorKind, CommentIntent, ContextCapabilities, Coverage, ErrorScope,
        ExternalResearchPolicy, RunError, RunInfo, SourceKind, Summary, REVIEW_ARTIFACT_SCHEMA,
    };

    fn request() -> ReviewRequest {
        serde_json::from_str(include_str!("../fixtures/requests/diff-only.json")).unwrap()
    }

    fn artifact(request: &ReviewRequest) -> ReviewArtifact {
        ReviewArtifact {
            schema_version: REVIEW_ARTIFACT_SCHEMA.to_string(),
            artifact_id: "artifact-1".to_string(),
            request_id: request.request_id.clone(),
            request_digest: request_digest(request).unwrap(),
            lifecycle_state: LifecycleState::Completed,
            verdict: Verdict::Warn,
            context_capabilities: ContextCapabilities::from_request(request),
            summary: Summary {
                title: "Review".to_string(),
                body: "Summary body".to_string(),
                analysis: String::new(),
                residual_risk: Vec::new(),
            },
            findings: Vec::new(),
            comments: vec![
                Comment {
                    id: "comment-001".to_string(),
                    kind: CommentKind::Inline,
                    intent: CommentIntent::Finding,
                    finding_id: None,
                    body: "Changed line".to_string(),
                    anchor: Anchor {
                        kind: AnchorKind::Inline,
                        path: Some("src/ratio.rs".to_string()),
                        line: Some(3),
                        start_line: None,
                        end_line: None,
                        hunk_digest: None,
                    },
                    dedupe_key: Some("ratio-zero".to_string()),
                    suggested_fixes: Vec::new(),
                },
                Comment {
                    id: "comment-002".to_string(),
                    kind: CommentKind::Inline,
                    intent: CommentIntent::Finding,
                    finding_id: None,
                    body: "Unchanged line".to_string(),
                    anchor: Anchor {
                        kind: AnchorKind::Inline,
                        path: Some("src/ratio.rs".to_string()),
                        line: Some(6),
                        start_line: None,
                        end_line: None,
                        hunk_digest: None,
                    },
                    dedupe_key: None,
                    suggested_fixes: Vec::new(),
                },
            ],
            suggested_fixes: Vec::new(),
            citations: Vec::new(),
            receipts: Vec::new(),
            run: RunInfo {
                engine_version: "test".to_string(),
                config_digest: "sha256:test".to_string(),
                started_at: "0".to_string(),
                finished_at: "0".to_string(),
                duration_ms: 1,
                cost_usd: None,
                coverage: Coverage {
                    files_reviewed: Vec::new(),
                    files_with_findings: Vec::new(),
                },
            },
            errors: vec![RunError {
                scope: ErrorScope::Run,
                code: "ignored".to_string(),
                message: "ignored in planner".to_string(),
                retryable: false,
            }],
        }
    }

    #[test]
    fn maps_only_changed_new_side_lines() {
        let request = request();
        let changed = changed_new_lines_by_path(&request.change.diff.body).unwrap();
        let ratio_lines = changed.get("src/ratio.rs").unwrap();
        assert!(ratio_lines.contains(&2));
        assert!(ratio_lines.contains(&3));
        assert!(ratio_lines.contains(&4));
        assert!(!ratio_lines.contains(&1));
        assert!(!ratio_lines.contains(&6));
    }

    #[test]
    fn builds_inline_review_only_for_mappable_comments() {
        let request = request();
        assert_eq!(request.source.kind, SourceKind::Fixture);
        assert_eq!(
            request.policy.external_research,
            ExternalResearchPolicy::Forbid
        );
        let artifact = artifact(&request);
        let plan = build_post_plan(
            &request,
            &artifact,
            "example/fixture",
            7,
            SummaryTarget::CheckRun,
            &ExistingGithubState::default(),
        )
        .unwrap();
        let review = plan
            .operations
            .iter()
            .find(|operation| operation.id == "create-inline-review")
            .unwrap();
        assert_eq!(review.body["comments"].as_array().unwrap().len(), 1);
        assert_eq!(review.body["commit_id"], "0123456789abcdef");
        assert_eq!(review.body["comments"][0]["line"], 3);
        assert_eq!(plan.unmapped_comments[0].comment_id, "comment-002");
    }

    #[test]
    fn existing_markers_turn_creates_into_updates() {
        let request = request();
        let artifact = artifact(&request);
        let mut existing = ExistingGithubState {
            summary_comment_id: Some(101),
            ..ExistingGithubState::default()
        };
        existing
            .inline_comment_ids
            .insert("ratio-zero".to_string(), 201);
        existing.check_run_id = Some(501);
        let plan = build_post_plan(
            &request,
            &artifact,
            "example/fixture",
            7,
            SummaryTarget::CheckRun,
            &existing,
        )
        .unwrap();
        assert!(plan.operations.iter().any(|operation| {
            operation.method == "PATCH" && operation.path == "/repos/example/fixture/check-runs/501"
        }));
        let check_update = plan
            .operations
            .iter()
            .find(|operation| operation.id == "update-check-run")
            .unwrap();
        assert!(check_update.body.get("head_sha").is_none());
        assert!(plan.operations.iter().any(|operation| {
            operation.method == "PATCH"
                && operation.path == "/repos/example/fixture/issues/comments/101"
        }));
        assert!(plan.operations.iter().any(|operation| {
            operation.method == "PATCH"
                && operation.path == "/repos/example/fixture/pulls/comments/201"
        }));
        assert!(!plan
            .operations
            .iter()
            .any(|operation| operation.id == "create-inline-review"));
    }

    // Backlog 009: a classic-token operator hitting Checks-write denial
    // previously got a raw `gh` stderr dump with no hint that
    // --summary-target status is exactly the documented fallback. Pins the
    // actionable message.
    #[test]
    fn check_run_403_names_the_summary_target_status_fallback() {
        let fake_gh = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("fixtures/bin/fake-gh");
        let client = GithubClient::new(fake_gh.display().to_string()).with_token("test-token");
        let plan = PostPlan {
            schema_version: POST_PLAN_SCHEMA.to_string(),
            repo: "example/fixture".to_string(),
            pull_request: 7,
            head_sha: "0123456789abcdef".to_string(),
            artifact_id: "artifact-1".to_string(),
            artifact_digest: "sha256:test".to_string(),
            summary_target: SummaryTarget::CheckRun,
            operations: vec![PlannedOperation {
                id: "create-check-run".to_string(),
                method: "POST".to_string(),
                path: "/repos/example/fixture/check-runs".to_string(),
                description: "create check run".to_string(),
                idempotency_key: "create-check-run".to_string(),
                body: serde_json::json!({}),
            }],
            unmapped_comments: Vec::new(),
        };

        std::env::set_var("CERBERUS_FAKE_GH_FAIL_CHECK_RUNS_403", "1");
        let err = client.apply_plan(&plan).unwrap_err();
        std::env::remove_var("CERBERUS_FAKE_GH_FAIL_CHECK_RUNS_403");

        let message = err.to_string();
        assert!(
            message.contains("--summary-target status"),
            "error should name the concrete fallback: {message}"
        );
        assert!(
            message.contains("Checks-write"),
            "error should name what's missing: {message}"
        );
    }
}
