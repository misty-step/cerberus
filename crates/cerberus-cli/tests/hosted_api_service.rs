use serde_json::Value;
use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
    time::{SystemTime, UNIX_EPOCH},
};

#[test]
fn hosted_api_service_fixture_health_bypasses_auth() {
    let temp = temp_dir("health");
    let out = temp.join("health.json");

    let status = command("GET", "/api/health", &out)
        .status()
        .expect("run command");

    assert!(status.success(), "expected success, got {status}");
    let report = read_json(&out);
    assert_eq!(
        report["schema_version"],
        "hosted-api-service-fixture-report.v1"
    );
    assert_eq!(report["http_status"], 200);
    assert_eq!(report["body"]["status"], "ok");
}

#[test]
fn hosted_api_service_fixture_requires_auth_for_status() {
    let temp = temp_dir("missing-auth");
    let out = temp.join("missing-auth.json");

    let status = command("GET", "/api/reviews/77", &out)
        .status()
        .expect("run command");

    assert!(status.success(), "fixture reports rejected request");
    let report = read_json(&out);
    assert_eq!(report["http_status"], 401);
    assert_eq!(report["body"]["error"], "missing_or_invalid_auth");
    let raw = fs::read_to_string(&out).expect("report");
    assert!(!raw.contains("fixture-api-key"));
}

#[test]
fn hosted_api_service_fixture_reads_queued_status() {
    let temp = temp_dir("queued");
    let out = temp.join("queued.json");

    let status = authed_command("GET", "/api/reviews/77", &out)
        .status()
        .expect("run command");

    assert!(status.success(), "expected success, got {status}");
    let report = read_json(&out);
    assert_eq!(report["http_status"], 200);
    assert_eq!(report["body"]["review_id"], 77);
    assert_eq!(report["body"]["status"], "queued");
    assert_eq!(report["body"]["repo"], "misty-step/cerberus");
}

#[test]
fn hosted_api_service_fixture_maps_unavailable_status_store() {
    let temp = temp_dir("read-unavailable");
    let out = temp.join("read-unavailable.json");

    let status = authed_command_with_store(
        "GET",
        "/api/reviews/77",
        &out,
        &fixture("service-store-unavailable.json"),
    )
    .status()
    .expect("run command");

    assert!(status.success(), "fixture reports unavailable store");
    let report = read_json(&out);
    assert_eq!(report["http_status"], 500);
    assert_eq!(report["body"]["error"], "store_unavailable");
}

#[test]
fn hosted_api_service_fixture_writes_post_store_error_without_token_leak() {
    let temp = temp_dir("store-error");
    let out = temp.join("store-error.json");

    let status = authed_command_with_store(
        "POST",
        "/api/reviews",
        &out,
        &fixture("service-store-error.json"),
    )
    .arg("--body")
    .arg(fixture("create-review-valid.json"))
    .status()
    .expect("run command");

    assert!(status.success(), "fixture reports store error");
    let raw = fs::read_to_string(&out).expect("report");
    assert!(!raw.contains("fixture-api-key"));
    assert!(!raw.contains("fixture-request-token"));
    assert!(!raw.contains("github_token"));

    let report = read_json(&out);
    assert_eq!(report["http_status"], 500);
    assert_eq!(report["body"]["error"], "store_error");
}

#[test]
fn hosted_api_service_fixture_writes_queued_post_response() {
    let temp = temp_dir("post-queued");
    let out = temp.join("post-queued.json");

    let status = authed_command("POST", "/api/reviews", &out)
        .arg("--body")
        .arg(fixture("create-review-valid.json"))
        .status()
        .expect("run command");

    assert!(status.success(), "expected success, got {status}");
    let report = read_json(&out);
    assert_eq!(report["http_status"], 202);
    assert_eq!(report["body"]["review_id"], 77);
    assert_eq!(report["body"]["status"], "queued");
    assert_eq!(report["dispatch_request"]["repo"], "misty-step/cerberus");
    assert_eq!(report["dispatch_request"]["github_token_present"], true);
}

#[test]
fn validate_accepts_versioned_hosted_api_review_store() {
    let status = Command::new(env!("CARGO_BIN_EXE_cerberus-cli"))
        .arg("validate")
        .arg(fixture("service-store.json"))
        .status()
        .expect("run validate");

    assert!(status.success(), "versioned store should validate");
}

#[test]
fn validate_accepts_legacy_omitted_version_hosted_api_review_store() {
    let temp = temp_dir("legacy-validate");
    let store = temp.join("legacy-store.json");
    fs::write(
        &store,
        r#"{
          "next_review_id": 77,
          "create_outcome": "created",
          "reviews": {}
        }"#,
    )
    .expect("write legacy store");

    let status = Command::new(env!("CARGO_BIN_EXE_cerberus-cli"))
        .arg("validate")
        .arg(&store)
        .status()
        .expect("run validate");

    assert!(
        status.success(),
        "legacy omitted-version store should validate"
    );
}

#[test]
fn validate_rejects_empty_unversioned_hosted_api_review_store() {
    let temp = temp_dir("empty-validate");
    let store = temp.join("empty-store.json");
    fs::write(&store, "{}").expect("write empty store");

    let output = Command::new(env!("CARGO_BIN_EXE_cerberus-cli"))
        .arg("validate")
        .arg(&store)
        .output()
        .expect("run validate");

    assert!(
        !output.status.success(),
        "empty unversioned store should not validate"
    );
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("missing schema_version"),
        "stderr was {stderr}"
    );
}

#[test]
fn hosted_api_service_fixture_rejects_invalid_store_without_output() {
    let temp = temp_dir("invalid-store");
    let out = temp.join("queued.json");
    let store = temp.join("store.json");
    fs::write(
        &store,
        r#"{
          "schema_version": "hosted-api-review-store.v999",
          "next_review_id": 77,
          "create_outcome": "created",
          "reviews": {}
        }"#,
    )
    .expect("write invalid store");

    let output = authed_command_with_store("GET", "/api/reviews/77", &out, &store)
        .output()
        .expect("run command");

    assert!(!output.status.success(), "invalid store should fail closed");
    assert!(!out.exists(), "invalid store should not write a report");
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("unsupported version"),
        "stderr was {stderr}"
    );
}

#[test]
fn hosted_api_service_fixture_rejects_empty_store_without_output() {
    let temp = temp_dir("empty-store");
    let out = temp.join("queued.json");
    let store = temp.join("store.json");
    fs::write(&store, "{}").expect("write empty store");

    let output = authed_command_with_store("GET", "/api/reviews/77", &out, &store)
        .output()
        .expect("run command");

    assert!(!output.status.success(), "empty store should fail closed");
    assert!(!out.exists(), "empty store should not write a report");
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("missing schema_version"),
        "stderr was {stderr}"
    );
}

#[test]
fn hosted_api_service_fixture_rejects_top_level_token_store_without_output() {
    let temp = temp_dir("top-level-token-store");
    let out = temp.join("queued.json");
    let store = temp.join("store.json");
    fs::write(
        &store,
        r#"{
          "schema_version": "hosted-api-review-store.v1",
          "next_review_id": 77,
          "create_outcome": "created",
          "github_token": "fixture-request-token",
          "reviews": {}
        }"#,
    )
    .expect("write invalid store");

    let output = authed_command_with_store("GET", "/api/reviews/77", &out, &store)
        .output()
        .expect("run command");

    assert!(
        !output.status.success(),
        "top-level token should fail closed"
    );
    assert!(!out.exists(), "top-level token should not write a report");
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("unknown field"), "stderr was {stderr}");
}

fn authed_command(method: &str, path: &str, out: &Path) -> Command {
    authed_command_with_store(method, path, out, &fixture("service-store.json"))
}

fn authed_command_with_store(method: &str, path: &str, out: &Path, store: &Path) -> Command {
    let mut command = command(method, path, out);
    command
        .arg("--authorization")
        .arg("Bearer fixture-api-key")
        .arg("--store")
        .arg(store);
    command
}

fn command(method: &str, path: &str, out: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_cerberus-cli"));
    command
        .arg("hosted-api-service-fixture")
        .arg("--method")
        .arg(method)
        .arg("--path")
        .arg(path)
        .arg("--api-key")
        .arg("fixture-api-key")
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
        "cerberus-hosted-api-service-{name}-{}-{nanos}",
        std::process::id()
    ));
    fs::create_dir_all(&path).expect("temp dir");
    path
}
