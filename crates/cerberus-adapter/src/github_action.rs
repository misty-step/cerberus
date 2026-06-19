use crate::{changed_files_from_git_diff, AdapterError};
use cerberus_schema::{
    Caller, Change, ReviewContext, ReviewPolicy, ReviewRequest, ReviewSource,
    REVIEW_REQUEST_VERSION,
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "decision", rename_all = "snake_case")]
pub enum GithubActionReviewDecision {
    Review {
        request: ReviewRequest,
    },
    Skip {
        reason: GithubActionSkipReason,
        message: String,
    },
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum GithubActionSkipReason {
    ForkPullRequest,
    DraftPullRequest,
}

pub fn github_action_review_decision_from_event(
    event_json: &str,
    diff: &str,
    caller_run_id: impl Into<String>,
) -> Result<GithubActionReviewDecision, AdapterError> {
    let event: GithubPullRequestEvent =
        serde_json::from_str(event_json).map_err(AdapterError::GithubActionEvent)?;
    github_action_review_decision(event, diff, caller_run_id)
}

pub fn github_action_skip_decision_from_event(
    event_json: &str,
) -> Result<Option<GithubActionReviewDecision>, AdapterError> {
    let event: GithubPullRequestEvent =
        serde_json::from_str(event_json).map_err(AdapterError::GithubActionEvent)?;
    Ok(github_action_skip_decision(&event.pull_request))
}

fn github_action_review_decision(
    event: GithubPullRequestEvent,
    diff: &str,
    caller_run_id: impl Into<String>,
) -> Result<GithubActionReviewDecision, AdapterError> {
    let pr = event.pull_request;

    if let Some(decision) = github_action_skip_decision(&pr) {
        return Ok(decision);
    }

    let files = changed_files_from_git_diff(diff)?;
    let repository = pr.base.repo.full_name;
    let head_repo = pr
        .head
        .repo
        .map(|repo| repo.full_name)
        .unwrap_or_else(|| "<missing>".to_string());
    let request_id = format!(
        "github-pr-{}-{}-{}",
        repository.replace('/', "-"),
        pr.number,
        short_sha(&pr.head.sha)
    );
    let linked_artifacts = vec![format!("github://{repository}/pull/{}", pr.number)];
    let mut metadata = BTreeMap::new();
    metadata.insert("action".to_string(), event.action);
    metadata.insert("base_repo".to_string(), repository.clone());
    metadata.insert("head_repo".to_string(), head_repo);

    let request = ReviewRequest {
        schema_version: REVIEW_REQUEST_VERSION.to_string(),
        request_id,
        source: ReviewSource::GithubPr {
            repository,
            pr_number: pr.number,
            base_ref: pr.base.ref_name.clone(),
            head_ref: pr.head.ref_name.clone(),
            head_sha: Some(pr.head.sha.clone()),
        },
        change: Change {
            title: pr.title,
            description: pr.body,
            base_ref: Some(pr.base.ref_name),
            head_ref: Some(pr.head.ref_name),
            head_sha: Some(pr.head.sha),
            diff: diff.to_string(),
            files,
        },
        context: ReviewContext {
            summary: Some("GitHub Actions pull_request event.".to_string()),
            acceptance: vec![],
            linked_artifacts,
            metadata,
        },
        caller: Caller {
            name: "github-actions".to_string(),
            run_id: caller_run_id.into(),
        },
        policy: ReviewPolicy::default(),
    };
    request.validate()?;
    Ok(GithubActionReviewDecision::Review { request })
}

fn github_action_skip_decision(pr: &GithubPullRequest) -> Option<GithubActionReviewDecision> {
    let head_repo = pr.head.repo.as_ref().map(|repo| repo.full_name.as_str());
    if head_repo != Some(pr.base.repo.full_name.as_str()) {
        return Some(GithubActionReviewDecision::Skip {
            reason: GithubActionSkipReason::ForkPullRequest,
            message: "Cerberus: skipping fork PR (no secrets available)".to_string(),
        });
    }

    if pr.draft {
        return Some(GithubActionReviewDecision::Skip {
            reason: GithubActionSkipReason::DraftPullRequest,
            message: "Cerberus: skipping draft PR".to_string(),
        });
    }

    None
}

fn short_sha(sha: &str) -> String {
    sha.chars().take(12).collect()
}

#[derive(Debug, Deserialize)]
struct GithubPullRequestEvent {
    action: String,
    pull_request: GithubPullRequest,
}

#[derive(Debug, Deserialize)]
struct GithubPullRequest {
    number: u64,
    title: String,
    #[serde(default)]
    body: Option<String>,
    #[serde(default)]
    draft: bool,
    base: GithubPullRequestBaseSide,
    head: GithubPullRequestHeadSide,
}

#[derive(Debug, Deserialize)]
struct GithubPullRequestBaseSide {
    #[serde(rename = "ref")]
    ref_name: String,
    repo: GithubRepository,
}

#[derive(Debug, Deserialize)]
struct GithubPullRequestHeadSide {
    #[serde(rename = "ref")]
    ref_name: String,
    sha: String,
    #[serde(default)]
    repo: Option<GithubRepository>,
}

#[derive(Debug, Deserialize)]
struct GithubRepository {
    full_name: String,
}

#[cfg(test)]
mod tests {
    use super::*;

    const OPENED_EVENT: &str =
        include_str!("../../../fixtures/github-actions/pull-request-opened.json");
    const FORK_EVENT: &str =
        include_str!("../../../fixtures/github-actions/pull-request-fork.json");
    const DRAFT_EVENT: &str =
        include_str!("../../../fixtures/github-actions/pull-request-draft.json");
    const MISSING_HEAD_REPO_EVENT: &str =
        include_str!("../../../fixtures/github-actions/pull-request-missing-head-repo.json");
    const DIFF: &str = include_str!("../../../fixtures/github-actions/pull-request.diff");

    #[test]
    fn github_action_builds_review_request_for_same_repo_pr() {
        let decision = github_action_review_decision_from_event(OPENED_EVENT, DIFF, "gha-run-021")
            .expect("same-repo event builds");
        let GithubActionReviewDecision::Review { request } = decision else {
            panic!("expected review request");
        };

        request.validate().expect("request validates");
        assert_eq!(
            request.request_id,
            "github-pr-misty-step-cerberus-459-abc123def456"
        );
        assert_eq!(request.caller.name, "github-actions");
        assert_eq!(request.caller.run_id, "gha-run-021");
        assert_eq!(request.change.files.len(), 2);
        assert_eq!(request.change.files[0].path, "README.md");
        assert_eq!(request.change.files[0].additions, 1);
        assert_eq!(request.change.files[0].deletions, 1);
        assert_eq!(request.context.metadata["action"], "opened");
        assert_eq!(
            request.context.linked_artifacts,
            vec!["github://misty-step/cerberus/pull/459"]
        );
        assert!(matches!(
            request.source,
            ReviewSource::GithubPr {
                repository,
                pr_number: 459,
                ..
            } if repository == "misty-step/cerberus"
        ));
    }

    #[test]
    fn github_action_skips_fork_prs_before_diff_parsing() {
        let decision =
            github_action_review_decision_from_event(FORK_EVENT, "not a diff", "gha-run-021")
                .expect("fork skip does not parse diff");

        assert_eq!(
            decision,
            GithubActionReviewDecision::Skip {
                reason: GithubActionSkipReason::ForkPullRequest,
                message: "Cerberus: skipping fork PR (no secrets available)".to_string(),
            }
        );
    }

    #[test]
    fn github_action_skips_prs_with_missing_head_repo_before_diff_parsing() {
        let decision = github_action_review_decision_from_event(
            MISSING_HEAD_REPO_EVENT,
            "not a diff",
            "gha-run-021",
        )
        .expect("missing head repo skip does not parse diff");

        assert_eq!(
            decision,
            GithubActionReviewDecision::Skip {
                reason: GithubActionSkipReason::ForkPullRequest,
                message: "Cerberus: skipping fork PR (no secrets available)".to_string(),
            }
        );
    }

    #[test]
    fn github_action_skips_draft_prs_before_diff_parsing() {
        let decision =
            github_action_review_decision_from_event(DRAFT_EVENT, "not a diff", "gha-run-021")
                .expect("draft skip does not parse diff");

        assert_eq!(
            decision,
            GithubActionReviewDecision::Skip {
                reason: GithubActionSkipReason::DraftPullRequest,
                message: "Cerberus: skipping draft PR".to_string(),
            }
        );
    }

    #[test]
    fn github_action_rejects_malformed_same_repo_diff() {
        let error =
            github_action_review_decision_from_event(OPENED_EVENT, "not a diff", "gha-run-021")
                .expect_err("malformed diff rejects");

        assert!(error
            .to_string()
            .contains("must start with a diff --git header"));
    }
}
