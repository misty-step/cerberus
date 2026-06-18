use cerberus_adapter::CommandHarness;
use cerberus_core::review_with_harness;
use cerberus_schema::{
    Change, ChangedFile, FileStatus, ReviewConfig, ReviewContext, ReviewRequest, ReviewSource,
    ReviewerConfig, ReviewerStatus, Verdict, REVIEW_CONFIG_VERSION, REVIEW_REQUEST_VERSION,
};
use std::{collections::BTreeMap, path::Path, time::Duration};

#[test]
fn peer_harness_command_profile_runs_through_command_harness() {
    let profiles = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join("fixtures/harnesses/peer-command-profiles.json");
    let harness = CommandHarness::new(env!("CARGO_BIN_EXE_cerberus-peer-harness"))
        .args([
            "--harness".to_string(),
            "pi".to_string(),
            "--profiles".to_string(),
            profiles.display().to_string(),
        ])
        .timeout(Duration::from_secs(5));

    let artifact =
        review_with_harness(&request(), &config(), &harness).expect("peer harness command runs");

    assert_eq!(artifact.verdict, Verdict::Skip);
    assert!(artifact.degraded);
    assert_eq!(
        artifact.reviewer_artifacts[0].status,
        ReviewerStatus::Degraded
    );
    assert!(artifact.reviewer_artifacts[0]
        .degraded_reason
        .as_deref()
        .is_some_and(|reason| reason.contains("live \"pi\" execution is disabled")));
    artifact.validate().expect("run artifact validates");
}

fn config() -> ReviewConfig {
    ReviewConfig {
        schema_version: REVIEW_CONFIG_VERSION.to_string(),
        config_id: "peer-runner-command-test".to_string(),
        reviewers: vec![ReviewerConfig {
            id: "peer-runner-reviewer".to_string(),
            perspective: "correctness".to_string(),
            model: "openrouter/test-model".to_string(),
            fake_behavior: Default::default(),
        }],
        confidence_min: 0.7,
    }
}

fn request() -> ReviewRequest {
    ReviewRequest {
        schema_version: REVIEW_REQUEST_VERSION.to_string(),
        request_id: "peer-runner-command-request".to_string(),
        source: ReviewSource::Fixture {
            name: "peer-runner-command".to_string(),
        },
        change: Change {
            title: "Peer runner command fixture".to_string(),
            description: None,
            base_ref: None,
            head_ref: None,
            head_sha: Some("peer-runner-command-sha".to_string()),
            diff: "diff --git a/src/lib.rs b/src/lib.rs\n+peer harness command\n".to_string(),
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
