use serde_json::{json, Value};
use std::{
    fs,
    io::{Read, Write},
    net::TcpStream,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

#[test]
fn hosted_api_worker_fixture_completes_queued_review() {
    let temp = temp_dir("worker-complete");
    let store_state = temp.join("store-state.json");
    fs::copy(fixture("service-store.json"), &store_state).expect("seed store state");
    let out = temp.join("worker");

    let output = Command::new(env!("CARGO_BIN_EXE_cerberus-cli"))
        .arg("hosted-api-worker-fixture")
        .arg("--store-state")
        .arg(&store_state)
        .arg("--review-id")
        .arg("77")
        .arg("--pr-context")
        .arg(fixture("pull-request-context.json"))
        .arg("--diff-file")
        .arg(github_fixture("pull-request.diff"))
        .arg("--out")
        .arg(&out)
        .output()
        .expect("run worker fixture");

    assert!(
        output.status.success(),
        "worker fixture failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        String::from_utf8_lossy(&output.stdout).contains("completed-status.json"),
        "worker stdout should name completed status"
    );

    let review_request = read_json(&out.join("review-request.json"));
    assert_eq!(review_request["source"]["kind"], "github_pr");
    assert_eq!(review_request["source"]["head_sha"], "abc123def456");
    assert_eq!(review_request["change"]["head_sha"], "abc123def456");
    let artifact_json = read_json(&out.join("review-run-artifact.json"));
    let artifact: cerberus_schema::ReviewRunArtifact =
        serde_json::from_value(artifact_json.clone()).expect("artifact parses");
    artifact.validate().expect("artifact validates");
    assert_eq!(artifact.reviewed_head_sha.as_deref(), Some("abc123def456"));

    let completed = read_json(&out.join("completed-status.json"));
    assert_eq!(completed["status"], "completed");
    assert_eq!(
        completed["aggregated_verdict"]["verdict"],
        artifact.verdict.as_str()
    );
    assert_eq!(completed["review_run_artifact"], artifact_json);

    let persisted = fs::read_to_string(&store_state).expect("store state persisted");
    let persisted_json: Value = serde_json::from_str(&persisted).expect("persisted store parses");
    assert_eq!(persisted_json["reviews"]["77"]["status"], "completed");
    assert_eq!(
        persisted_json["reviews"]["77"]["review_run_artifact"],
        artifact_json
    );
    assert!(!persisted.contains("fixture-api-key"));
    assert!(!persisted.contains("fixture-request-token"));
    assert!(!persisted.contains("github_token"));

    let mut server = FixtureServer::start_stateful(&temp, &store_state, 1);
    let replayed = request(
        &server.addr,
        "GET",
        "/api/reviews/77",
        Some("Bearer fixture-api-key"),
        None,
    );

    assert_eq!(replayed.status, 200);
    assert_eq!(replayed.body["status"], "completed");
    assert_eq!(replayed.body["review_run_artifact"], artifact_json);
    assert!(!replayed.raw_body.contains("fixture-api-key"));
    assert!(!replayed.raw_body.contains("fixture-request-token"));
    assert!(!replayed.raw_body.contains("github_token"));
    server.join();
}

#[test]
fn hosted_api_worker_fixture_rejects_head_mismatch_without_mutating_store() {
    let temp = temp_dir("worker-head-mismatch");
    let store_state = temp.join("store-state.json");
    fs::copy(fixture("service-store.json"), &store_state).expect("seed store state");
    let before = fs::read_to_string(&store_state).expect("read initial state");
    let out = temp.join("worker");
    fs::create_dir_all(&out).expect("create stale worker dir");
    let stale_paths = [
        out.join("review-request.json"),
        out.join("review-run-artifact.json"),
        out.join("completed-status.json"),
    ];
    for path in &stale_paths {
        fs::write(path, "stale worker evidence").expect("write stale worker output");
    }

    let output = Command::new(env!("CARGO_BIN_EXE_cerberus-cli"))
        .arg("hosted-api-worker-fixture")
        .arg("--store-state")
        .arg(&store_state)
        .arg("--review-id")
        .arg("77")
        .arg("--pr-context")
        .arg(fixture("pull-request-context-wrong-head.json"))
        .arg("--diff-file")
        .arg(github_fixture("pull-request.diff"))
        .arg("--out")
        .arg(&out)
        .output()
        .expect("run worker fixture");

    assert!(!output.status.success(), "head mismatch should fail closed");
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("head_sha"), "stderr was {stderr}");
    for path in &stale_paths {
        assert!(
            !path.exists(),
            "failed worker should remove stale output {}",
            path.display()
        );
    }
    let after = fs::read_to_string(&store_state).expect("read final state");
    assert_eq!(after, before, "failed worker must not mutate store state");
}

#[test]
fn hosted_api_worker_fixture_rejects_state_output_path_collision() {
    let temp = temp_dir("worker-state-output-collision");
    let out = temp.join("worker");
    fs::create_dir_all(&out).expect("create worker dir");
    let store_state = out.join("review-request.json");
    fs::copy(fixture("service-store.json"), &store_state).expect("seed colliding store state");
    let before = fs::read_to_string(&store_state).expect("read initial state");

    let output = Command::new(env!("CARGO_BIN_EXE_cerberus-cli"))
        .arg("hosted-api-worker-fixture")
        .arg("--store-state")
        .arg(&store_state)
        .arg("--review-id")
        .arg("77")
        .arg("--pr-context")
        .arg(fixture("pull-request-context.json"))
        .arg("--diff-file")
        .arg(github_fixture("pull-request.diff"))
        .arg("--out")
        .arg(&out)
        .output()
        .expect("run worker fixture");

    assert!(
        !output.status.success(),
        "path collision should fail closed"
    );
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("--store-state must not be one of the worker output files"),
        "stderr was {stderr}"
    );
    let after = fs::read_to_string(&store_state).expect("read final state");
    assert_eq!(
        after, before,
        "state/output collision must not remove state"
    );
    assert!(!out.join("review-run-artifact.json").exists());
    assert!(!out.join("completed-status.json").exists());
}

#[test]
fn hosted_api_fixture_server_serves_contract_over_http() {
    let temp = temp_dir("contract");
    let mut server = FixtureServer::start(&temp, "service-store.json", 4);

    let health = request(&server.addr, "GET", "/api/health", None, None);
    assert_eq!(health.status, 200);
    assert_eq!(health.body["status"], "ok");

    let missing_auth = request(&server.addr, "GET", "/api/reviews/77", None, None);
    assert_eq!(missing_auth.status, 401);
    assert_eq!(missing_auth.body["error"], "missing_or_invalid_auth");

    let queued = request(
        &server.addr,
        "GET",
        "/api/reviews/77",
        Some("Bearer fixture-api-key"),
        None,
    );
    assert_eq!(queued.status, 200);
    assert_eq!(queued.body["review_id"], 77);
    assert_eq!(queued.body["status"], "queued");

    let create_body = fs::read_to_string(fixture("create-review-valid.json")).expect("body");
    let created = request(
        &server.addr,
        "POST",
        "/api/reviews",
        Some("Bearer fixture-api-key"),
        Some(&create_body),
    );
    assert_eq!(created.status, 202);
    assert_eq!(created.body["review_id"], 77);
    assert_eq!(created.body["status"], "queued");
    assert!(!created.raw_body.contains("fixture-api-key"));
    assert!(!created.raw_body.contains("fixture-request-token"));
    assert!(!created.raw_body.contains("github_token"));

    server.join();
}

#[test]
fn hosted_api_fixture_server_maps_store_error_over_http() {
    let temp = temp_dir("store-error");
    let mut server = FixtureServer::start(&temp, "service-store-error.json", 1);
    let create_body = fs::read_to_string(fixture("create-review-valid.json")).expect("body");

    let response = request(
        &server.addr,
        "POST",
        "/api/reviews",
        Some("Bearer fixture-api-key"),
        Some(&create_body),
    );

    assert_eq!(response.status, 500);
    assert_eq!(response.body["error"], "store_error");
    assert!(!response.raw_body.contains("fixture-api-key"));
    assert!(!response.raw_body.contains("fixture-request-token"));
    server.join();
}

#[test]
fn hosted_api_fixture_server_persists_posted_reviews() {
    let temp = temp_dir("stateful-store");
    let store_state = temp.join("store-state.json");
    let mut server = FixtureServer::start_stateful(&temp, &store_state, 2);
    let create_body = fs::read_to_string(fixture("create-review-valid.json")).expect("body");

    let created = request(
        &server.addr,
        "POST",
        "/api/reviews",
        Some("Bearer fixture-api-key"),
        Some(&create_body),
    );

    assert_eq!(created.status, 202);
    let review_id = created.body["review_id"].as_u64().expect("review id");
    assert_eq!(review_id, 1);
    assert_eq!(created.body["status"], "queued");

    let status_path = format!("/api/reviews/{review_id}");
    let status = request(
        &server.addr,
        "GET",
        &status_path,
        Some("Bearer fixture-api-key"),
        None,
    );

    assert_eq!(status.status, 200);
    assert_eq!(status.body["review_id"], review_id);
    assert_eq!(status.body["repo"], "misty-step/cerberus");
    assert_eq!(status.body["pr_number"], 459);
    assert_eq!(status.body["head_sha"], "abc123def456");
    assert_eq!(status.body["status"], "queued");
    assert_eq!(status.body["aggregated_verdict"], Value::Null);

    server.join();

    let persisted = fs::read_to_string(&store_state).expect("store state written");
    assert!(persisted.contains(&format!("\"{review_id}\"")));
    assert!(persisted.contains(&format!("\"next_review_id\":{}", review_id + 1)));
    assert!(!persisted.contains("fixture-api-key"));
    assert!(!persisted.contains("fixture-request-token"));
    assert!(!persisted.contains("github_token"));
}

#[test]
fn hosted_api_fixture_server_maps_state_collision_to_store_error() {
    let temp = temp_dir("stateful-store-collision");
    let store_state = temp.join("store-state.json");
    fs::write(
        &store_state,
        serde_json::to_string(&json!({
            "next_review_id": 1,
            "create_outcome": "created",
            "read_unavailable": false,
            "reviews": {
                "1": {
                    "review_id": 1,
                    "repo": "misty-step/cerberus",
                    "pr_number": 459,
                    "head_sha": "abc123def456",
                    "status": "queued",
                    "aggregated_verdict": null,
                    "completed_at": null,
                    "inserted_at": "1970-01-01T00:00:00Z"
                }
            }
        }))
        .expect("state json"),
    )
    .expect("write state");
    let mut server = FixtureServer::start_stateful(&temp, &store_state, 1);
    let create_body = fs::read_to_string(fixture("create-review-valid.json")).expect("body");

    let response = request(
        &server.addr,
        "POST",
        "/api/reviews",
        Some("Bearer fixture-api-key"),
        Some(&create_body),
    );

    assert_eq!(response.status, 500);
    assert_eq!(response.body["error"], "store_error");
    assert!(!response.raw_body.contains("fixture-api-key"));
    assert!(!response.raw_body.contains("fixture-request-token"));
    server.join();
}

#[test]
fn hosted_api_fixture_server_checks_auth_before_body_json() {
    let temp = temp_dir("auth-before-body");
    let mut server = FixtureServer::start(&temp, "service-store.json", 1);

    let response = request(&server.addr, "POST", "/api/reviews", None, Some("{"));

    assert_eq!(response.status, 401);
    assert_eq!(response.body["error"], "missing_or_invalid_auth");
    server.join();
}

#[test]
fn hosted_api_fixture_server_rejects_invalid_store_before_ready() {
    assert_fixture_server_rejects_store_before_ready(
        "invalid-store-before-ready",
        r#"{
          "schema_version": "hosted-api-review-store.v999",
          "next_review_id": 77,
          "create_outcome": "created",
          "reviews": {}
        }"#,
        "unsupported version",
    );
}

#[test]
fn hosted_api_fixture_server_rejects_empty_store_before_ready() {
    assert_fixture_server_rejects_store_before_ready(
        "empty-store-before-ready",
        "{}",
        "missing schema_version",
    );
}

fn assert_fixture_server_rejects_store_before_ready(
    temp_name: &str,
    store_raw: &str,
    expected_stderr: &str,
) {
    let temp = temp_dir(temp_name);
    let store_state = temp.join("store-state.json");
    let ready = temp.join("ready.txt");
    fs::write(&store_state, store_raw).expect("write invalid state");

    let mut child = Command::new(env!("CARGO_BIN_EXE_cerberus-cli"))
        .arg("hosted-api-serve-fixture")
        .arg("--addr")
        .arg("127.0.0.1:0")
        .arg("--api-key")
        .arg("fixture-api-key")
        .arg("--store-state")
        .arg(&store_state)
        .arg("--ready-file")
        .arg(&ready)
        .arg("--max-requests")
        .arg("1")
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn fixture server");

    let deadline = Instant::now() + Duration::from_secs(5);
    let mut stderr = String::new();
    loop {
        if ready.exists() {
            let _ = child.kill();
            let _ = child.wait();
            panic!("invalid store must not write ready file");
        }
        if let Some(status) = child.try_wait().expect("server status") {
            if let Some(mut handle) = child.stderr.take() {
                let _ = handle.read_to_string(&mut stderr);
            }
            assert!(!status.success(), "invalid store should fail closed");
            break;
        }
        assert!(
            Instant::now() < deadline,
            "fixture server did not reject invalid store"
        );
        thread::sleep(Duration::from_millis(25));
    }

    assert!(
        !ready.exists(),
        "invalid store should not publish readiness"
    );
    assert!(stderr.contains(expected_stderr), "stderr was {stderr}");
}

#[test]
fn hosted_api_fixture_server_rejects_non_loopback_bind() {
    let temp = temp_dir("non-loopback");
    let ready = temp.join("ready.txt");

    let output = Command::new(env!("CARGO_BIN_EXE_cerberus-cli"))
        .arg("hosted-api-serve-fixture")
        .arg("--addr")
        .arg("0.0.0.0:0")
        .arg("--api-key")
        .arg("fixture-api-key")
        .arg("--ready-file")
        .arg(&ready)
        .output()
        .expect("run fixture server");

    assert!(!output.status.success(), "non-loopback bind should fail");
    assert!(
        !ready.exists(),
        "non-loopback bind should not write ready file"
    );
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains("only supports loopback bind addresses"));
}

#[test]
fn hosted_api_fixture_server_accepts_bare_ready_file() {
    let temp = temp_dir("bare-ready");
    let mut child = Command::new(env!("CARGO_BIN_EXE_cerberus-cli"))
        .current_dir(&temp)
        .arg("hosted-api-serve-fixture")
        .arg("--addr")
        .arg("127.0.0.1:0")
        .arg("--api-key")
        .arg("fixture-api-key")
        .arg("--ready-file")
        .arg("ready.txt")
        .arg("--max-requests")
        .arg("1")
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
        .expect("spawn fixture server");
    let addr = wait_for_ready(&temp.join("ready.txt"), &mut child);

    let response = request(&addr, "GET", "/api/health", None, None);

    assert_eq!(response.status, 200);
    let status = child.wait().expect("server exits");
    assert!(status.success(), "fixture server exited with {status}");
}

struct FixtureServer {
    child: Child,
    addr: String,
}

impl FixtureServer {
    fn start(temp: &Path, store_name: &str, max_requests: u64) -> Self {
        let ready = temp.join("ready.txt");
        let mut child = Command::new(env!("CARGO_BIN_EXE_cerberus-cli"))
            .arg("hosted-api-serve-fixture")
            .arg("--addr")
            .arg("127.0.0.1:0")
            .arg("--api-key")
            .arg("fixture-api-key")
            .arg("--store")
            .arg(fixture(store_name))
            .arg("--ready-file")
            .arg(&ready)
            .arg("--max-requests")
            .arg(max_requests.to_string())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .spawn()
            .expect("spawn fixture server");
        let addr = wait_for_ready(&ready, &mut child);
        Self { child, addr }
    }

    fn start_stateful(temp: &Path, store_state: &Path, max_requests: u64) -> Self {
        let ready = temp.join("ready.txt");
        let mut child = Command::new(env!("CARGO_BIN_EXE_cerberus-cli"))
            .arg("hosted-api-serve-fixture")
            .arg("--addr")
            .arg("127.0.0.1:0")
            .arg("--api-key")
            .arg("fixture-api-key")
            .arg("--store-state")
            .arg(store_state)
            .arg("--ready-file")
            .arg(&ready)
            .arg("--max-requests")
            .arg(max_requests.to_string())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .spawn()
            .expect("spawn stateful fixture server");
        let addr = wait_for_ready(&ready, &mut child);
        Self { child, addr }
    }

    fn join(&mut self) {
        let status = self.child.wait().expect("server exits");
        assert!(status.success(), "fixture server exited with {status}");
    }
}

impl Drop for FixtureServer {
    fn drop(&mut self) {
        if self.child.try_wait().expect("server status").is_none() {
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
    }
}

struct HttpResponse {
    status: u16,
    body: Value,
    raw_body: String,
}

fn request(
    addr: &str,
    method: &str,
    path: &str,
    authorization: Option<&str>,
    body: Option<&str>,
) -> HttpResponse {
    let mut stream = TcpStream::connect(addr).expect("connect fixture server");
    stream
        .set_read_timeout(Some(Duration::from_secs(5)))
        .expect("read timeout");
    let body = body.unwrap_or("");
    let mut raw = format!(
        "{method} {path} HTTP/1.1\r\nHost: {addr}\r\nContent-Length: {}\r\nConnection: close\r\n",
        body.len()
    );
    if let Some(authorization) = authorization {
        raw.push_str(&format!("Authorization: {authorization}\r\n"));
    }
    if !body.is_empty() {
        raw.push_str("Content-Type: application/json\r\n");
    }
    raw.push_str("\r\n");
    raw.push_str(body);
    stream.write_all(raw.as_bytes()).expect("write request");

    let mut response = String::new();
    stream.read_to_string(&mut response).expect("read response");
    parse_response(&response)
}

fn parse_response(response: &str) -> HttpResponse {
    let (headers, raw_body) = response
        .split_once("\r\n\r\n")
        .expect("response header separator");
    let status = headers
        .lines()
        .next()
        .expect("status line")
        .split_whitespace()
        .nth(1)
        .expect("status code")
        .parse::<u16>()
        .expect("status code integer");
    let body = serde_json::from_str(raw_body).expect("response body json");
    HttpResponse {
        status,
        body,
        raw_body: raw_body.to_string(),
    }
}

fn wait_for_ready(ready: &Path, child: &mut Child) -> String {
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        if let Ok(addr) = fs::read_to_string(ready) {
            return addr.trim().to_string();
        }
        if let Some(status) = child.try_wait().expect("server status") {
            let mut stderr = String::new();
            if let Some(mut handle) = child.stderr.take() {
                let _ = handle.read_to_string(&mut stderr);
            }
            panic!("fixture server exited before ready file with {status}: {stderr}");
        }
        assert!(
            Instant::now() < deadline,
            "fixture server did not write ready file"
        );
        thread::sleep(Duration::from_millis(25));
    }
}

fn fixture(name: &str) -> PathBuf {
    workspace_root().join("fixtures/hosted-api").join(name)
}

fn github_fixture(name: &str) -> PathBuf {
    workspace_root().join("fixtures/github-actions").join(name)
}

fn read_json(path: &Path) -> Value {
    let raw = fs::read_to_string(path).expect("read json");
    serde_json::from_str(&raw).expect("json parses")
}

fn workspace_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("crates")
        .parent()
        .expect("workspace")
        .to_path_buf()
}

fn temp_dir(name: &str) -> PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time")
        .as_nanos();
    let path = std::env::temp_dir().join(format!(
        "cerberus-hosted-api-server-{name}-{}-{nanos}",
        std::process::id()
    ));
    fs::create_dir_all(&path).expect("temp dir");
    path
}
