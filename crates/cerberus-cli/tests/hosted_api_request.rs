use serde_json::Value;
use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
    time::{SystemTime, UNIX_EPOCH},
};

#[test]
fn hosted_api_request_fixture_writes_valid_review_request_without_token_leak() {
    let temp = temp_dir("valid");
    let out = temp.join("review-request.json");

    let status = command(&out)
        .arg("--run-id")
        .arg("hosted-api-run-005")
        .status()
        .expect("run command");

    assert!(status.success(), "expected success, got {status}");
    let raw = fs::read_to_string(&out).expect("request");
    assert!(!raw.contains("fixture-request-token"));
    assert!(!raw.contains("github_token_present"));

    let request = read_json(&out);
    assert_eq!(request["schema_version"], "review-request.v1");
    assert_eq!(
        request["request_id"],
        "hosted-api-github-pr-misty-step-cerberus-459-abc123def456"
    );
    assert_eq!(request["caller"]["name"], "hosted-api");
    assert_eq!(request["caller"]["run_id"], "hosted-api-run-005");
    assert_eq!(request["source"]["kind"], "github_pr");
    assert_eq!(request["source"]["repository"], "misty-step/cerberus");
    assert_eq!(request["source"]["pr_number"], 459);
    assert_eq!(request["source"]["head_sha"], "abc123def456");
    assert_eq!(
        request["change"]["files"].as_array().expect("files").len(),
        2
    );
    assert_eq!(
        request["context"]["linked_artifacts"][0],
        "github://misty-step/cerberus/pull/459"
    );
}

#[test]
fn hosted_api_request_fixture_removes_stale_output_on_head_sha_mismatch() {
    let temp = temp_dir("wrong-head");
    let out = temp.join("review-request.json");
    fs::write(&out, "stale").expect("stale output");

    let status = command(&out)
        .arg("--pr-context")
        .arg(fixture("pull-request-context-wrong-head.json"))
        .status()
        .expect("run command");

    assert!(!status.success(), "head-sha mismatch should fail");
    assert!(
        !out.exists(),
        "stale output should be removed before failure"
    );
}

fn command(out: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_cerberus-cli"));
    command
        .arg("hosted-api-request-fixture")
        .arg("--body")
        .arg(fixture("create-review-valid.json"))
        .arg("--pr-context")
        .arg(fixture("pull-request-context.json"))
        .arg("--diff-file")
        .arg(workspace_root().join("fixtures/github-actions/pull-request.diff"))
        .arg("--out")
        .arg(out);
    command
}

fn fixture(name: &str) -> PathBuf {
    workspace_root().join("fixtures/hosted-api").join(name)
}

fn workspace_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("crates")
        .parent()
        .expect("workspace")
        .to_path_buf()
}

fn read_json(path: &Path) -> Value {
    serde_json::from_str(&fs::read_to_string(path).expect("json file")).expect("json")
}

fn temp_dir(name: &str) -> PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time")
        .as_nanos();
    let path = std::env::temp_dir().join(format!(
        "cerberus-hosted-api-request-{name}-{}-{nanos}",
        std::process::id()
    ));
    fs::create_dir_all(&path).expect("temp dir");
    path
}
