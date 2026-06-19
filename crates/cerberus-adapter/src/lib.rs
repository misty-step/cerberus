use cerberus_schema::{
    Caller, Change, Finding, InlineCommentCandidate, ReviewContext, ReviewPolicy, ReviewRequest,
    ReviewRunArtifact, ReviewSource, Verdict, INLINE_COMMENT_CANDIDATE_VERSION,
    REVIEW_REQUEST_VERSION,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::path::PathBuf;

mod artifact_store;
mod command_harness;
mod git_diff;
mod github_action;
mod hosted_api;
mod thinktank_migration;
pub use artifact_store::{FileReviewRunArtifactStore, ReviewRunArtifactStore};
pub use command_harness::{
    BoundedCommand, BoundedCommandOutput, CommandHarness, CommandHarnessInput,
};
pub use git_diff::changed_files_from_git_diff;
pub use github_action::{
    github_action_review_decision_from_event, github_action_skip_decision_from_event,
    GithubActionReviewDecision, GithubActionSkipReason,
};
pub use hosted_api::{
    run_hosted_api_dispatch, run_hosted_api_dispatch_fixture, HostedApiDispatchConfig,
    HostedApiDispatchDecision, HostedApiDispatchOutcome, HostedApiDispatchRequest,
    HostedApiDispatchSettings, HostedApiDispatchTranscript, HostedApiDispatchTransport,
    HostedApiHttpResponse,
};
pub use thinktank_migration::{
    import_thinktank_historical_run, ThinkTankHistoricalRun, ThinkTankMigrationOutput,
};

#[derive(Debug, thiserror::Error)]
pub enum AdapterError {
    #[error(transparent)]
    Schema(#[from] cerberus_schema::SchemaError),
    #[error("caller {actual:?} does not match expected caller {expected:?}")]
    CallerMismatch {
        expected: &'static str,
        actual: String,
    },
    #[error("caller fixture references forbidden sibling term {term:?}")]
    ForbiddenSiblingReference { term: &'static str },
    #[error("failed to parse GitHub pull_request event: {0}")]
    GithubActionEvent(#[source] serde_json::Error),
    #[error("invalid hosted API dispatch transcript: {reason}")]
    HostedApiDispatchTranscript { reason: String },
    #[error("invalid git diff: {reason}")]
    InvalidGitDiff { reason: String },
    #[error("artifact has no reviewed head sha for caller projection")]
    MissingReviewedHeadSha,
    #[error("review run artifact file IO failed for {path:?}: {source}")]
    ArtifactStoreIo {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("review run artifact already exists at {path:?}")]
    ArtifactAlreadyExists { path: PathBuf },
    #[error("review run id {run_id:?} is not safe for artifact storage")]
    UnsafeArtifactRunId { run_id: String },
    #[error("review run artifact path expected run_id {expected:?}, got {actual:?}")]
    ArtifactRunIdMismatch { expected: String, actual: String },
    #[error("{field} mismatch: expected {expected:?}, got {actual:?}")]
    RequestArtifactMismatch {
        field: &'static str,
        expected: String,
        actual: String,
    },
    #[error("serialization failed: {0}")]
    Serialization(#[from] serde_json::Error),
    #[error("historical ThinkTank fixture has unsupported version {actual:?}")]
    UnsupportedThinkTankFixtureVersion { actual: String },
    #[error("historical ThinkTank fixture has no reviewer agents")]
    MissingThinkTankAgents,
    #[error("historical ThinkTank agent {agent:?} has unsupported status {status:?}")]
    UnsupportedThinkTankAgentStatus { agent: String, status: String },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CallerKind {
    Bitterblossom,
    OlympusArgus,
}

impl CallerKind {
    pub fn caller_name(self) -> &'static str {
        match self {
            CallerKind::Bitterblossom => "bitterblossom",
            CallerKind::OlympusArgus => "olympus-argus",
        }
    }

    pub fn forbidden_sibling_terms(self) -> &'static [&'static str] {
        match self {
            CallerKind::Bitterblossom => &[
                "olympus",
                "argus",
                "adminifi/olympus",
                "/users/phaedrus/development/adminifi/olympus",
                "argus-github",
                "argus-review-poster",
                "argusreview",
                "ArgusReviewArtifact",
                "ArgusReviewEvent",
                "PostArgusReview",
            ],
            CallerKind::OlympusArgus => &[
                "bitterblossom",
                "misty-step/bitterblossom",
                "/Users/phaedrus/Development/bitterblossom",
                "Bitterblossom",
                "run ledger",
                "task/agent/trigger/run",
            ],
        }
    }
}

#[derive(Debug, Clone)]
pub struct CallerReviewRequestBuilder {
    request_id: String,
    source: ReviewSource,
    change: Change,
    context: ReviewContext,
    caller: Caller,
    policy: ReviewPolicy,
}

impl CallerReviewRequestBuilder {
    pub fn new(
        request_id: impl Into<String>,
        caller: CallerKind,
        run_id: impl Into<String>,
        source: ReviewSource,
        change: Change,
    ) -> Self {
        Self {
            request_id: request_id.into(),
            source,
            change,
            context: ReviewContext {
                summary: None,
                acceptance: vec![],
                linked_artifacts: vec![],
                metadata: Default::default(),
            },
            caller: Caller {
                name: caller.caller_name().to_string(),
                run_id: run_id.into(),
            },
            policy: ReviewPolicy::default(),
        }
    }

    pub fn summary(mut self, summary: impl Into<String>) -> Self {
        self.context.summary = Some(summary.into());
        self
    }

    pub fn acceptance(mut self, acceptance: impl Into<String>) -> Self {
        self.context.acceptance.push(acceptance.into());
        self
    }

    pub fn linked_artifact(mut self, artifact: impl Into<String>) -> Self {
        self.context.linked_artifacts.push(artifact.into());
        self
    }

    pub fn metadata(mut self, key: impl Into<String>, value: impl Into<String>) -> Self {
        self.context.metadata.insert(key.into(), value.into());
        self
    }

    pub fn policy(mut self, policy: ReviewPolicy) -> Self {
        self.policy = policy;
        self
    }

    pub fn build(self) -> Result<ReviewRequest, AdapterError> {
        let request = ReviewRequest {
            schema_version: REVIEW_REQUEST_VERSION.to_string(),
            request_id: self.request_id,
            source: self.source,
            change: self.change,
            context: self.context,
            caller: self.caller,
            policy: self.policy,
        };
        request.validate()?;
        Ok(request)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct BitterblossomRunReceipt {
    pub caller: String,
    pub task_id: String,
    pub caller_run_id: String,
    pub review_run_id: String,
    pub request_id: String,
    pub artifact_path: String,
}

impl BitterblossomRunReceipt {
    pub fn from_artifact(
        task_id: impl Into<String>,
        ledger_root: impl AsRef<str>,
        request: &ReviewRequest,
        artifact: &ReviewRunArtifact,
    ) -> Result<Self, AdapterError> {
        ensure_caller(request, CallerKind::Bitterblossom)?;
        validate_artifact_for_request(request, artifact)?;
        let caller_run_id = request.caller.run_id.clone();
        Ok(Self {
            caller: request.caller.name.clone(),
            task_id: task_id.into(),
            artifact_path: format!(
                "{}/{}/artifacts/{}.json",
                ledger_root.as_ref().trim_end_matches('/'),
                caller_run_id,
                artifact.run_id
            ),
            caller_run_id,
            review_run_id: artifact.run_id.clone(),
            request_id: artifact.request_id.clone(),
        })
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct OlympusArgusProjection {
    pub caller: String,
    pub request_id: String,
    pub reviewed_head_sha: String,
    pub verdict: Verdict,
    pub summary: String,
    pub posting_policy_owner: String,
    pub inline_comments: Vec<InlineCommentCandidate>,
}

impl OlympusArgusProjection {
    pub fn from_artifact(
        request: &ReviewRequest,
        artifact: &ReviewRunArtifact,
    ) -> Result<Self, AdapterError> {
        ensure_caller(request, CallerKind::OlympusArgus)?;
        validate_artifact_for_request(request, artifact)?;
        let reviewed_head_sha = artifact
            .reviewed_head_sha
            .clone()
            .ok_or(AdapterError::MissingReviewedHeadSha)?;
        Ok(Self {
            caller: request.caller.name.clone(),
            request_id: artifact.request_id.clone(),
            reviewed_head_sha,
            verdict: artifact.verdict,
            summary: artifact.summary.clone(),
            posting_policy_owner: "olympus-argus".to_string(),
            inline_comments: render_inline_comment_candidates(artifact),
        })
    }
}

pub fn assert_no_cross_caller_references(
    caller: CallerKind,
    fixture_text: &str,
) -> Result<(), AdapterError> {
    let lower = fixture_text.to_lowercase();
    for term in caller.forbidden_sibling_terms() {
        if lower.contains(&term.to_lowercase()) {
            return Err(AdapterError::ForbiddenSiblingReference { term });
        }
    }
    Ok(())
}

fn ensure_caller(request: &ReviewRequest, expected: CallerKind) -> Result<(), AdapterError> {
    request.validate()?;
    let expected_name = expected.caller_name();
    if request.caller.name != expected_name {
        return Err(AdapterError::CallerMismatch {
            expected: expected_name,
            actual: request.caller.name.clone(),
        });
    }
    Ok(())
}

pub fn validate_artifact_for_request(
    request: &ReviewRequest,
    artifact: &ReviewRunArtifact,
) -> Result<(), AdapterError> {
    request.validate()?;
    artifact.validate()?;
    if artifact.request_id != request.request_id {
        return Err(AdapterError::RequestArtifactMismatch {
            field: "request_id",
            expected: request.request_id.clone(),
            actual: artifact.request_id.clone(),
        });
    }
    let expected_digest = digest_json(request)?;
    if artifact.request_digest != expected_digest {
        return Err(AdapterError::RequestArtifactMismatch {
            field: "request_digest",
            expected: expected_digest,
            actual: artifact.request_digest.clone(),
        });
    }
    if let Some(expected_head_sha) = &request.change.head_sha {
        let actual = artifact.reviewed_head_sha.clone().unwrap_or_default();
        if actual != *expected_head_sha {
            return Err(AdapterError::RequestArtifactMismatch {
                field: "reviewed_head_sha",
                expected: expected_head_sha.clone(),
                actual,
            });
        }
    }
    Ok(())
}

fn render_inline_comment_candidates(artifact: &ReviewRunArtifact) -> Vec<InlineCommentCandidate> {
    artifact
        .findings
        .iter()
        .map(|finding| InlineCommentCandidate {
            schema_version: INLINE_COMMENT_CANDIDATE_VERSION.to_string(),
            finding_id: finding.id.clone(),
            reviewer_id: finding.reviewer_id.clone(),
            perspective: finding.perspective.clone(),
            path: finding.citation.path.clone(),
            line: finding.citation.line.unwrap_or(1),
            severity: finding.severity,
            body: inline_comment_body(finding),
        })
        .collect()
}

fn inline_comment_body(finding: &Finding) -> String {
    format!(
        "**{}** `{}`: {}\n\n{}\n\nEvidence: `{}`",
        finding.severity.as_str(),
        finding.category,
        finding.title,
        finding.description,
        finding.evidence
    )
}

fn digest_json<T: Serialize>(value: &T) -> Result<String, AdapterError> {
    let json = serde_json::to_vec(value)?;
    let mut hasher = Sha256::new();
    hasher.update(json);
    Ok(format!("{:x}", hasher.finalize()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use cerberus_core::{default_config, review};
    use cerberus_schema::{ChangedFile, FileStatus, RenderTarget};

    const BITTERBLOSSOM_FIXTURE: &str =
        include_str!("../../../fixtures/callers/bitterblossom-task.json");
    const OLYMPUS_FIXTURE: &str = include_str!("../../../fixtures/callers/olympus-argus.json");

    #[test]
    fn caller_contracts_bitterblossom_fixture_invokes_core_and_receipts_ledger_path() {
        assert_no_cross_caller_references(CallerKind::Bitterblossom, BITTERBLOSSOM_FIXTURE)
            .expect("fixture stays independent");
        let request: ReviewRequest =
            serde_json::from_str(BITTERBLOSSOM_FIXTURE).expect("fixture parses");
        request.validate().expect("request validates");
        let built = bitterblossom_request_from_builder().expect("builder emits request");
        assert_eq!(request, built);

        let artifact = review(&request, &default_config()).expect("core review succeeds");
        artifact.validate().expect("artifact validates");
        let receipt = BitterblossomRunReceipt::from_artifact(
            "review-factory-smoke",
            "ledger/reviews",
            &request,
            &artifact,
        )
        .expect("receipt projects");

        assert_eq!(receipt.caller, "bitterblossom");
        assert_eq!(receipt.caller_run_id, "bb-run-20260618-001");
        assert!(receipt
            .artifact_path
            .starts_with("ledger/reviews/bb-run-20260618-001/artifacts/"));

        let other_request = olympus_request_from_builder().expect("builder emits request");
        assert!(BitterblossomRunReceipt::from_artifact(
            "review-factory-smoke",
            "ledger/reviews",
            &other_request,
            &artifact,
        )
        .is_err());
    }

    #[test]
    fn caller_contracts_olympus_fixture_invokes_core_and_projects_argus_comments() {
        assert_no_cross_caller_references(CallerKind::OlympusArgus, OLYMPUS_FIXTURE)
            .expect("fixture stays independent");
        let request: ReviewRequest = serde_json::from_str(OLYMPUS_FIXTURE).expect("fixture parses");
        request.validate().expect("request validates");
        let built = olympus_request_from_builder().expect("builder emits request");
        assert_eq!(request, built);

        let artifact = review(&request, &default_config()).expect("core review succeeds");
        artifact.validate().expect("artifact validates");
        let projection =
            OlympusArgusProjection::from_artifact(&request, &artifact).expect("projection builds");

        assert_eq!(projection.caller, "olympus-argus");
        assert_eq!(projection.reviewed_head_sha, "olympusheadsha001");
        assert_eq!(projection.posting_policy_owner, "olympus-argus");
        assert!(!projection.inline_comments.is_empty());

        let other_request = bitterblossom_request_from_builder().expect("builder emits request");
        assert!(OlympusArgusProjection::from_artifact(&other_request, &artifact).is_err());
    }

    #[test]
    fn caller_contracts_no_cross_caller_reference_guard_rejects_sibling_terms() {
        for sample in [
            "argus marker",
            "ArgusReviewArtifact",
            "/Users/phaedrus/Development/adminifi/olympus",
        ] {
            assert!(assert_no_cross_caller_references(CallerKind::Bitterblossom, sample).is_err());
        }
        for sample in [
            "bitterblossom run ledger",
            "misty-step/bitterblossom",
            "/Users/phaedrus/Development/bitterblossom",
        ] {
            assert!(assert_no_cross_caller_references(CallerKind::OlympusArgus, sample).is_err());
        }
    }

    fn bitterblossom_request_from_builder() -> Result<ReviewRequest, AdapterError> {
        CallerReviewRequestBuilder::new(
            "caller-bitterblossom-review-factory-smoke",
            CallerKind::Bitterblossom,
            "bb-run-20260618-001",
            ReviewSource::External {
                system: "event-plane-task".to_string(),
                id: "review-factory-smoke".to_string(),
            },
            Change {
                title: "Review factory smoke task".to_string(),
                description: Some("A caller-owned task submits source-agnostic review input and stores the returned artifact in its run ledger.".to_string()),
                base_ref: None,
                head_ref: None,
                head_sha: Some("bbheadsha001".to_string()),
                diff: "diff --git a/src/review_factory.rs b/src/review_factory.rs\n--- a/src/review_factory.rs\n+++ b/src/review_factory.rs\n@@ -1,3 +1,4 @@\n pub fn build() {\n+    // CERBERUS_FAKE_FINDING\n }\n".to_string(),
                files: vec![ChangedFile {
                    path: "src/review_factory.rs".to_string(),
                    status: FileStatus::Modified,
                    additions: 1,
                    deletions: 0,
                }],
            },
        )
        .summary("Event-plane task fixture for a code review workload.")
        .acceptance("Caller owns trigger, run ledger, retries, and budget envelope.")
        .acceptance("Cerberus owns only review request validation and review artifact production.")
        .linked_artifact("task://review-factory-smoke")
        .metadata("task_id", "review-factory-smoke")
        .metadata("trigger_id", "manual-contract-fixture")
        .metadata("run_ledger_root", "ledger/reviews")
        .policy(ReviewPolicy {
            render_targets: vec![RenderTarget::Json, RenderTarget::Markdown],
            allow_degraded: true,
            max_cost_usd: Some(2.0),
            override_approval: None,
        })
        .build()
    }

    fn olympus_request_from_builder() -> Result<ReviewRequest, AdapterError> {
        CallerReviewRequestBuilder::new(
            "caller-olympus-argus-smoke",
            CallerKind::OlympusArgus,
            "olympus-run-20260618-001",
            ReviewSource::GithubPr {
                repository: "adminifi/olympus".to_string(),
                pr_number: 88,
                base_ref: "main".to_string(),
                head_ref: "argus-contract-smoke".to_string(),
                head_sha: Some("olympusheadsha001".to_string()),
            },
            Change {
                title: "Argus posting projection smoke".to_string(),
                description: Some("A caller-owned GitHub review poster submits review input and keeps posting policy outside Cerberus.".to_string()),
                base_ref: Some("main".to_string()),
                head_ref: Some("argus-contract-smoke".to_string()),
                head_sha: Some("olympusheadsha001".to_string()),
                diff: "diff --git a/orchestrator/src/review.ts b/orchestrator/src/review.ts\n--- a/orchestrator/src/review.ts\n+++ b/orchestrator/src/review.ts\n@@ -1,3 +1,4 @@\n export function review() {\n+  // CERBERUS_FAKE_FINDING\n }\n".to_string(),
                files: vec![ChangedFile {
                    path: "orchestrator/src/review.ts".to_string(),
                    status: FileStatus::Modified,
                    additions: 1,
                    deletions: 0,
                }],
            },
        )
        .summary("GitHub PR fixture for caller-owned posting policy.")
        .acceptance("Caller owns activation gates, stale-head suppression, marker dedupe, caps, and posting.")
        .acceptance("Cerberus emits a validated review artifact and inline-comment projection only.")
        .linked_artifact("github://adminifi/olympus/pull/88")
        .metadata("request_marker", "contract-smoke")
        .metadata("max_findings", "10")
        .metadata("max_inline_comments", "5")
        .policy(ReviewPolicy {
            render_targets: vec![RenderTarget::Json],
            allow_degraded: false,
            max_cost_usd: Some(2.0),
            override_approval: None,
        })
        .build()
    }
}
