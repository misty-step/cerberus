use std::path::PathBuf;
use std::time::Duration;

use cerberus::{
    ReviewKernel, ReviewRequest, ReviewSubstrate, RunPolicy, REVIEW_ARTIFACT_SCHEMA,
    WORKFLOW_LOCK_PATH_ENV,
};

#[test]
fn kernel_review_runs_fixture_through_small_typed_boundary() {
    // `ReviewKernel::review` acquires the global review-workflow lock at a
    // well-known default path shared by every `cerberus` invocation on this
    // host (see `crate::workflow_lock`). Point this test at an isolated,
    // per-test lock path instead — otherwise this test would contend with a
    // real review running concurrently on the same machine, or with another
    // test binary that also exercises `ReviewKernel::review`, and fail with
    // `WorkflowLockError::Contended` instead of proving anything about the
    // kernel's own contract.
    let lock_dir = tempfile::tempdir().expect("create scratch dir for the workflow lock");
    let lock_path = lock_dir.path().join("review-kernel-test.lock");
    // SAFETY: this is the only test in this integration-test binary (each
    // `tests/*.rs` file compiles to its own process), so no other test can
    // observe this env var mid-mutation.
    unsafe {
        std::env::set_var(WORKFLOW_LOCK_PATH_ENV, &lock_path);
    }

    let request: ReviewRequest =
        serde_json::from_str(include_str!("../fixtures/requests/diff-only.json")).unwrap();
    let kernel = ReviewKernel::new(ReviewSubstrate::fixture(PathBuf::from(
        "fixtures/harness/valid-review.txt",
    )));
    let policy = RunPolicy {
        timeout: Duration::from_secs(5),
        failure_transcript: None,
    };

    let run = kernel.review(&request, &policy).unwrap();

    assert_eq!(run.artifact.schema_version, REVIEW_ARTIFACT_SCHEMA);
    assert_eq!(run.execution_plan.harness, "fixture");
    assert_eq!(run.execution_plan.prompt_transport, "fixture template");
    assert_eq!(run.telemetry, Default::default());
    assert!(!run.transcript.is_empty());
}
