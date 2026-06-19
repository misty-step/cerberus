use serde_json::Value;
use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
    time::{SystemTime, UNIX_EPOCH},
};

#[test]
fn hosted_api_ingress_fixture_writes_accepted_report_without_token_leak() {
    let temp = temp_dir("valid");
    let out = temp.join("report.json");

    let status = Command::new(env!("CARGO_BIN_EXE_cerberus-cli"))
        .arg("hosted-api-ingress-fixture")
        .arg("--body")
        .arg(fixture("create-review-valid.json"))
        .arg("--out")
        .arg(&out)
        .arg("--review-id")
        .arg("77")
        .status()
        .expect("run command");

    assert!(status.success(), "expected success, got {status}");
    let raw = fs::read_to_string(&out).expect("report");
    assert!(!raw.contains("fixture-request-token"));
    assert!(!raw.contains("extra_field"));

    let report = read_json(&out);
    assert_eq!(
        report["schema_version"],
        "hosted-api-ingress-fixture-report.v1"
    );
    assert_eq!(report["http_status"], 202);
    assert_eq!(report["body"]["review_id"], 77);
    assert_eq!(report["body"]["status"], "queued");
    assert_eq!(report["dispatch_request"]["repo"], "misty-step/cerberus");
    assert_eq!(report["dispatch_request"]["pr_number"], 459);
    assert_eq!(report["dispatch_request"]["head_sha"], "abc123def456");
    assert_eq!(report["dispatch_request"]["model"], "fake/model");
    assert_eq!(report["dispatch_request"]["github_token_present"], true);
}

#[test]
fn hosted_api_ingress_fixture_treats_blank_token_as_absent() {
    let temp = temp_dir("blank-token");
    let out = temp.join("report.json");

    let status = Command::new(env!("CARGO_BIN_EXE_cerberus-cli"))
        .arg("hosted-api-ingress-fixture")
        .arg("--body")
        .arg(fixture("create-review-whitespace-token.json"))
        .arg("--out")
        .arg(&out)
        .status()
        .expect("run command");

    assert!(status.success(), "expected success, got {status}");
    let report = read_json(&out);
    assert_eq!(report["http_status"], 202);
    assert_eq!(report["dispatch_request"]["github_token_present"], false);
}

#[test]
fn hosted_api_ingress_fixture_writes_validation_report_for_rejected_body() {
    let temp = temp_dir("invalid-token");
    let out = temp.join("report.json");

    let status = Command::new(env!("CARGO_BIN_EXE_cerberus-cli"))
        .arg("hosted-api-ingress-fixture")
        .arg("--body")
        .arg(fixture("create-review-invalid-token.json"))
        .arg("--out")
        .arg(&out)
        .status()
        .expect("run command");

    assert!(status.success(), "rejected body still writes parity report");
    let report = read_json(&out);
    assert_eq!(report["http_status"], 422);
    assert_eq!(report["body"]["error"], "invalid field: github_token");
    assert!(report.get("dispatch_request").is_none());
}

#[test]
fn hosted_api_ingress_fixture_preserves_legacy_missing_repo_error() {
    let temp = temp_dir("missing-repo");
    let out = temp.join("report.json");

    let status = Command::new(env!("CARGO_BIN_EXE_cerberus-cli"))
        .arg("hosted-api-ingress-fixture")
        .arg("--body")
        .arg(fixture("create-review-missing-repo.json"))
        .arg("--out")
        .arg(&out)
        .status()
        .expect("run command");

    assert!(status.success(), "rejected body still writes parity report");
    let report = read_json(&out);
    assert_eq!(report["http_status"], 422);
    assert_eq!(report["body"]["error"], "missing required field: repo");
    assert!(report.get("dispatch_request").is_none());
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
        "cerberus-hosted-api-ingress-{name}-{}-{nanos}",
        std::process::id()
    ));
    fs::create_dir_all(&path).expect("temp dir");
    path
}
