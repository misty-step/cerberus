use std::path::PathBuf;
use std::time::Duration;

use cerberus::{ReviewKernel, ReviewRequest, ReviewSubstrate, RunPolicy, REVIEW_ARTIFACT_SCHEMA};

#[test]
fn kernel_review_runs_fixture_through_small_typed_boundary() {
    let request: ReviewRequest =
        serde_json::from_str(include_str!("../fixtures/requests/diff-only.json")).unwrap();
    let kernel = ReviewKernel::new(ReviewSubstrate::fixture(PathBuf::from(
        "fixtures/harness/valid-review.txt",
    )));
    let policy = RunPolicy {
        cwd: PathBuf::from("."),
        timeout: Duration::from_secs(5),
        failure_transcript: None,
    };

    let run = kernel.review(&request, &policy).unwrap();

    assert_eq!(run.artifact.schema_version, REVIEW_ARTIFACT_SCHEMA);
    assert_eq!(run.execution_plan.harness, "fixture");
    assert_eq!(run.execution_plan.prompt_transport, "fixture template");
    assert!(!run.transcript.is_empty());
}
