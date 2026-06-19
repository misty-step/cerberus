use cerberus_adapter::{FileReviewRunArtifactStore, ReviewRunArtifactStore};
use cerberus_core::{default_config, review};
use cerberus_schema::{ReviewRequest, ReviewRunArtifact};
use serde_json::Value;
use std::{
    fs,
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    path::{Path, PathBuf},
    process::Command,
    sync::mpsc,
    thread,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

const CLEAN_REQUEST: &str = include_str!("../../../fixtures/review-request/clean.json");

#[test]
fn github_action_dispatch_posts_polls_and_writes_outputs() {
    let temp = temp_dir("pass");
    let output = temp.join("github-output.txt");
    let decision = temp.join("decision.json");
    let runner_temp = temp.join("runner-temp");
    fs::create_dir_all(&runner_temp).expect("runner temp");
    let server = FakeServer::start(vec![
        response(202, r#"{"review_id":"review-459"}"#),
        response(
            200,
            r#"{"status":"completed","aggregated_verdict":{"verdict":"PASS"}}"#,
        ),
    ]);

    let status = base_command(&server.base_url, &output, &decision, &runner_temp)
        .status()
        .expect("run command");

    assert!(status.success(), "expected success, got {status}");
    assert_eq!(
        fs::read_to_string(&output).expect("github output"),
        "review-id=review-459\nverdict=PASS\n"
    );
    let decision_json = read_json(&decision);
    assert_eq!(decision_json["outcome"], "completed");
    assert_eq!(decision_json["exit_code"], 0);
    assert_eq!(decision_json["elapsed_seconds"], 1);
    let verdict_json = read_json(&runner_temp.join("cerberus-api-verdict.json"));
    assert_eq!(verdict_json["aggregated_verdict"]["verdict"], "PASS");

    let requests = server.join();
    assert_eq!(requests.len(), 2);
    assert_eq!(requests[0].method, "POST");
    assert_eq!(requests[0].path, "/api/reviews");
    assert_eq!(
        requests[0].header("authorization"),
        Some("Bearer test-api-key")
    );
    let post_body: Value = serde_json::from_str(&requests[0].body).expect("post body json");
    assert_eq!(post_body["repo"], "misty-step/cerberus");
    assert_eq!(post_body["pr_number"], 459);
    assert_eq!(post_body["head_sha"], "abc123def456");
    assert_eq!(post_body["model"], "fake/model");
    assert_eq!(post_body["github_token"], "ghs_test_token");

    assert_eq!(requests[1].method, "GET");
    assert_eq!(requests[1].path, "/api/reviews/review-459");
    assert_eq!(
        requests[1].header("authorization"),
        Some("Bearer test-api-key")
    );
}

#[test]
fn github_action_dispatch_persists_completed_review_artifact_when_store_requested() {
    let temp = temp_dir("persist-artifact");
    let output = temp.join("github-output.txt");
    let decision = temp.join("decision.json");
    let runner_temp = temp.join("runner-temp");
    let store_root = temp.join("artifact-store");
    fs::create_dir_all(&runner_temp).expect("runner temp");
    let artifact = fixture_review_artifact();
    let completed = serde_json::json!({
        "status": "completed",
        "aggregated_verdict": { "verdict": "PASS" },
        "review_run_artifact": artifact.clone()
    })
    .to_string();
    let server = FakeServer::start(vec![
        response(202, r#"{"review_id":"review-459"}"#),
        response(200, completed),
    ]);

    let status = base_command(&server.base_url, &output, &decision, &runner_temp)
        .env("CERBERUS_ARTIFACT_STORE", &store_root)
        .status()
        .expect("run command");

    assert!(status.success(), "expected success, got {status}");
    assert_eq!(
        fs::read_to_string(&output).expect("github output"),
        "review-id=review-459\nverdict=PASS\n"
    );
    let decision_json = read_json(&decision);
    assert_eq!(decision_json["outcome"], "completed");
    assert_eq!(decision_json["verdict"], "PASS");
    assert_no_review_artifact_key(&decision_json);
    let verdict_json = read_json(&runner_temp.join("cerberus-api-verdict.json"));
    assert_no_review_artifact_key(&verdict_json);
    let store = FileReviewRunArtifactStore::new(&store_root);
    let artifact_path = store.artifact_path(&artifact.run_id).expect("safe id");
    assert!(artifact_path.exists(), "persisted artifact path missing");
    assert_eq!(
        store.get(&artifact.run_id).expect("artifact replays"),
        artifact
    );

    let requests = server.join();
    assert_eq!(requests.len(), 2);
}

#[test]
fn github_action_dispatch_does_not_serialize_artifact_without_store_request() {
    let temp = temp_dir("artifact-not-serialized");
    let output = temp.join("github-output.txt");
    let decision = temp.join("decision.json");
    let runner_temp = temp.join("runner-temp");
    fs::create_dir_all(&runner_temp).expect("runner temp");
    let artifact = fixture_review_artifact();
    let completed = serde_json::json!({
        "status": "completed",
        "aggregated_verdict": { "verdict": "PASS" },
        "review_run_artifact": artifact.clone(),
        "diagnostics": {
            "review_run_artifact": artifact.clone()
        },
        "events": [
            { "review_run_artifact": artifact }
        ]
    })
    .to_string();
    let server = FakeServer::start(vec![
        response(202, r#"{"review_id":"review-459"}"#),
        response(200, completed),
    ]);

    let status = base_command(&server.base_url, &output, &decision, &runner_temp)
        .status()
        .expect("run command");

    assert!(status.success(), "expected success, got {status}");
    let decision_json = read_json(&decision);
    assert_eq!(decision_json["outcome"], "completed");
    assert_eq!(decision_json["verdict"], "PASS");
    assert_no_review_artifact_key(&decision_json);
    let verdict_json = read_json(&runner_temp.join("cerberus-api-verdict.json"));
    assert_no_review_artifact_key(&verdict_json);

    let requests = server.join();
    assert_eq!(requests.len(), 2);
}

#[test]
fn github_action_dispatch_rejects_wrong_head_artifact_when_store_requested() {
    let temp = temp_dir("wrong-head-artifact");
    let output = temp.join("github-output.txt");
    let decision = temp.join("decision.json");
    let runner_temp = temp.join("runner-temp");
    let store_root = temp.join("artifact-store");
    fs::create_dir_all(&runner_temp).expect("runner temp");
    let artifact = fixture_review_artifact_for_head("different-head-sha");
    let completed = serde_json::json!({
        "status": "completed",
        "aggregated_verdict": { "verdict": "PASS" },
        "review_run_artifact": artifact
    })
    .to_string();
    let server = FakeServer::start(vec![
        response(202, r#"{"review_id":"review-459"}"#),
        response(200, completed),
    ]);

    let status = base_command(&server.base_url, &output, &decision, &runner_temp)
        .env("CERBERUS_ARTIFACT_STORE", &store_root)
        .status()
        .expect("run command");

    assert!(
        !status.success(),
        "mismatched artifact should fail before persistence"
    );
    assert!(
        !output.exists(),
        "outputs should not be written after invalid artifact"
    );
    assert!(
        !decision.exists(),
        "decision should not be written after invalid artifact"
    );
    assert!(!store_root.exists(), "store root should remain absent");

    let requests = server.join();
    assert_eq!(requests.len(), 2);
}

#[test]
fn hosted_api_dispatch_fixture_does_not_serialize_artifact_without_store_request() {
    let temp = temp_dir("fixture-artifact-not-serialized");
    let transcript = temp.join("transcript.json");
    let decision = temp.join("decision.json");
    fs::write(
        &transcript,
        fixture_transcript_json(fixture_review_artifact()),
    )
    .expect("transcript");

    let status = Command::new(env!("CARGO_BIN_EXE_cerberus-cli"))
        .arg("hosted-api-dispatch-fixture")
        .arg("--transcript")
        .arg(&transcript)
        .arg("--out")
        .arg(&decision)
        .status()
        .expect("run command");

    assert!(status.success(), "expected success, got {status}");
    let decision_json = read_json(&decision);
    assert_eq!(decision_json["outcome"], "completed");
    assert_eq!(decision_json["verdict"], "PASS");
    assert_no_review_artifact_key(&decision_json);
}

#[test]
fn github_action_dispatch_requires_artifact_when_store_requested() {
    let temp = temp_dir("missing-artifact");
    let output = temp.join("github-output.txt");
    let decision = temp.join("decision.json");
    let runner_temp = temp.join("runner-temp");
    let store_root = temp.join("artifact-store");
    fs::create_dir_all(&runner_temp).expect("runner temp");
    let server = FakeServer::start(vec![
        response(202, r#"{"review_id":"review-459"}"#),
        response(
            200,
            r#"{"status":"completed","aggregated_verdict":{"verdict":"PASS"}}"#,
        ),
    ]);

    let status = base_command(&server.base_url, &output, &decision, &runner_temp)
        .env("CERBERUS_ARTIFACT_STORE", &store_root)
        .status()
        .expect("run command");

    assert!(
        !status.success(),
        "explicit artifact store should fail without artifact"
    );
    assert!(
        !output.exists(),
        "outputs should not be written after store error"
    );
    assert!(
        !decision.exists(),
        "decision should not be written after store error"
    );
    assert!(!store_root.exists(), "store root should remain absent");

    let requests = server.join();
    assert_eq!(requests.len(), 2);
}

#[test]
fn github_action_dispatch_fail_verdict_exits_nonzero_after_outputs() {
    let temp = temp_dir("fail");
    let output = temp.join("github-output.txt");
    let decision = temp.join("decision.json");
    let runner_temp = temp.join("runner-temp");
    fs::create_dir_all(&runner_temp).expect("runner temp");
    let server = FakeServer::start(vec![
        response(202, r#"{"review_id":"review-459"}"#),
        response(
            200,
            r#"{"status":"completed","aggregated_verdict":{"verdict":"FAIL"}}"#,
        ),
    ]);

    let status = base_command(&server.base_url, &output, &decision, &runner_temp)
        .status()
        .expect("run command");

    assert!(!status.success(), "expected fail verdict to fail");
    assert_eq!(
        fs::read_to_string(&output).expect("github output"),
        "review-id=review-459\nverdict=FAIL\n"
    );
    let decision_json = read_json(&decision);
    assert_eq!(decision_json["outcome"], "completed");
    assert_eq!(decision_json["exit_code"], 1);
    assert_eq!(decision_json["verdict"], "FAIL");

    let requests = server.join();
    assert_eq!(requests.len(), 2);
}

#[test]
fn github_action_dispatch_rejects_unsafe_review_id_output() {
    let temp = temp_dir("unsafe-review-id");
    let output = temp.join("github-output.txt");
    let decision = temp.join("decision.json");
    let runner_temp = temp.join("runner-temp");
    fs::create_dir_all(&runner_temp).expect("runner temp");
    let server = FakeServer::start(vec![response(
        202,
        "{\"review_id\":\"review-459\\nverdict=PASS\"}",
    )]);

    let status = base_command(&server.base_url, &output, &decision, &runner_temp)
        .status()
        .expect("run command");

    assert!(!status.success(), "unsafe review id should fail closed");
    assert_eq!(
        fs::read_to_string(&output).expect("github output"),
        "review-id=\nverdict=SKIP\n"
    );
    let decision_json = read_json(&decision);
    assert_eq!(decision_json["outcome"], "invalid_dispatch_response");
    assert_eq!(decision_json["exit_code"], 1);

    let requests = server.join();
    assert_eq!(requests.len(), 1);
}

#[test]
fn github_action_dispatch_rejects_unsupported_verdict_output() {
    let temp = temp_dir("unsafe-verdict");
    let output = temp.join("github-output.txt");
    let decision = temp.join("decision.json");
    let runner_temp = temp.join("runner-temp");
    fs::create_dir_all(&runner_temp).expect("runner temp");
    let server = FakeServer::start(vec![
        response(202, r#"{"review_id":"review-459"}"#),
        response(
            200,
            "{\"status\":\"completed\",\"aggregated_verdict\":{\"verdict\":\"FAIL\\nverdict=PASS\"}}",
        ),
    ]);

    let status = base_command(&server.base_url, &output, &decision, &runner_temp)
        .status()
        .expect("run command");

    assert!(!status.success(), "unsupported verdict should fail closed");
    assert_eq!(
        fs::read_to_string(&output).expect("github output"),
        "review-id=review-459\nverdict=SKIP\n"
    );
    let decision_json = read_json(&decision);
    assert_eq!(decision_json["outcome"], "invalid_dispatch_response");
    assert_eq!(decision_json["verdict"], "SKIP");
    assert_eq!(decision_json["exit_code"], 1);

    let requests = server.join();
    assert_eq!(requests.len(), 2);
}

#[test]
fn github_action_dispatch_skips_fork_without_api_env() {
    let temp = temp_dir("fork");
    let output = temp.join("github-output.txt");

    let status = Command::new(env!("CARGO_BIN_EXE_cerberus-cli"))
        .env_clear()
        .arg("github-action-dispatch")
        .arg("--github-output")
        .arg(&output)
        .env("BASE_REPO", "misty-step/cerberus")
        .env("HEAD_REPO", "contributor/cerberus")
        .env("IS_DRAFT", "false")
        .status()
        .expect("run command");

    assert!(status.success(), "fork skip should succeed");
    assert_eq!(
        fs::read_to_string(&output).expect("github output"),
        "verdict=SKIP\nreview-id=\n"
    );
}

#[test]
fn github_action_dispatch_missing_api_key_writes_skip_and_fails() {
    let temp = temp_dir("missing-api-key");
    let output = temp.join("github-output.txt");

    let status = Command::new(env!("CARGO_BIN_EXE_cerberus-cli"))
        .env_clear()
        .arg("github-action-dispatch")
        .arg("--github-output")
        .arg(&output)
        .env("BASE_REPO", "misty-step/cerberus")
        .env("HEAD_REPO", "misty-step/cerberus")
        .env("IS_DRAFT", "false")
        .env("CERBERUS_URL", "http://127.0.0.1:1")
        .env("PR_NUMBER", "459")
        .env("HEAD_SHA", "abc123def456")
        .status()
        .expect("run command");

    assert!(!status.success(), "missing API key should fail");
    assert_eq!(
        fs::read_to_string(&output).expect("github output"),
        "verdict=SKIP\nreview-id=\n"
    );
}

fn base_command(base_url: &str, output: &Path, decision: &Path, runner_temp: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_cerberus-cli"));
    command
        .env_clear()
        .arg("github-action-dispatch")
        .arg("--github-output")
        .arg(output)
        .arg("--decision-out")
        .arg(decision)
        .env("BASE_REPO", "misty-step/cerberus")
        .env("HEAD_REPO", "misty-step/cerberus")
        .env("IS_DRAFT", "false")
        .env("CERBERUS_API_KEY", "test-api-key")
        .env("CERBERUS_URL", base_url)
        .env("PR_NUMBER", "459")
        .env("HEAD_SHA", "abc123def456")
        .env("CERBERUS_MODEL", "fake/model")
        .env("GITHUB_TOKEN", "ghs_test_token")
        .env("CERBERUS_TIMEOUT", "3")
        .env("CERBERUS_POLL_INTERVAL", "1")
        .env("RUNNER_TEMP", runner_temp);
    command
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
        "cerberus-github-action-dispatch-{name}-{}-{nanos}",
        std::process::id()
    ));
    fs::create_dir_all(&path).expect("temp dir");
    path
}

fn response(status: u16, body: impl Into<String>) -> FakeResponse {
    FakeResponse {
        status,
        body: body.into(),
    }
}

struct FakeResponse {
    status: u16,
    body: String,
}

struct FakeServer {
    base_url: String,
    handle: thread::JoinHandle<Vec<CapturedRequest>>,
}

impl FakeServer {
    fn start(responses: Vec<FakeResponse>) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind fake server");
        let base_url = format!("http://{}", listener.local_addr().expect("addr"));
        let (ready_tx, ready_rx) = mpsc::channel();
        let handle = thread::spawn(move || {
            ready_tx.send(()).expect("ready");
            let mut requests = Vec::new();
            for response in responses {
                let (mut stream, _) = listener.accept().expect("accept");
                requests.push(read_request(&mut stream));
                write_response(&mut stream, response);
            }
            requests
        });
        ready_rx.recv().expect("server ready");
        Self { base_url, handle }
    }

    fn join(self) -> Vec<CapturedRequest> {
        self.handle.join().expect("fake server joined")
    }
}

#[derive(Debug)]
struct CapturedRequest {
    method: String,
    path: String,
    headers: Vec<(String, String)>,
    body: String,
}

impl CapturedRequest {
    fn header(&self, name: &str) -> Option<&str> {
        self.headers
            .iter()
            .find(|(key, _)| key.eq_ignore_ascii_case(name))
            .map(|(_, value)| value.as_str())
    }
}

fn read_request(stream: &mut TcpStream) -> CapturedRequest {
    stream
        .set_read_timeout(Some(Duration::from_secs(5)))
        .expect("read timeout");
    let mut raw = Vec::new();
    let mut buf = [0; 1024];
    loop {
        let read = stream.read(&mut buf).expect("read request");
        assert!(read > 0, "connection closed before headers");
        raw.extend_from_slice(&buf[..read]);
        if raw.windows(4).any(|window| window == b"\r\n\r\n") {
            break;
        }
    }
    let header_end = raw
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .expect("header end")
        + 4;
    let headers_text = String::from_utf8(raw[..header_end].to_vec()).expect("headers utf8");
    let content_length = headers_text
        .lines()
        .find_map(|line| {
            let (name, value) = line.split_once(':')?;
            name.eq_ignore_ascii_case("content-length")
                .then(|| value.trim().parse::<usize>().expect("content length"))
        })
        .unwrap_or(0);
    while raw.len() < header_end + content_length {
        let read = stream.read(&mut buf).expect("read body");
        assert!(read > 0, "connection closed before body");
        raw.extend_from_slice(&buf[..read]);
    }
    let mut lines = headers_text.lines();
    let request_line = lines.next().expect("request line");
    let mut request_parts = request_line.split_whitespace();
    let method = request_parts.next().expect("method").to_string();
    let path = request_parts.next().expect("path").to_string();
    let headers = lines
        .filter_map(|line| {
            let (name, value) = line.split_once(':')?;
            Some((name.to_string(), value.trim().to_string()))
        })
        .collect();
    let body = String::from_utf8(raw[header_end..header_end + content_length].to_vec())
        .expect("body utf8");
    CapturedRequest {
        method,
        path,
        headers,
        body,
    }
}

fn write_response(stream: &mut TcpStream, response: FakeResponse) {
    let reason = if response.status == 202 {
        "Accepted"
    } else {
        "OK"
    };
    write!(
        stream,
        "HTTP/1.1 {} {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        response.status,
        reason,
        response.body.len(),
        response.body
    )
    .expect("write response");
}

fn fixture_review_artifact() -> ReviewRunArtifact {
    fixture_review_artifact_for_head("abc123def456")
}

fn fixture_review_artifact_for_head(head_sha: &str) -> ReviewRunArtifact {
    let mut request: ReviewRequest =
        serde_json::from_str(CLEAN_REQUEST).expect("request fixture parses");
    request.change.head_sha = Some(head_sha.to_string());
    review(&request, &default_config()).expect("core review succeeds")
}

fn fixture_transcript_json(artifact: ReviewRunArtifact) -> String {
    serde_json::json!({
        "api_base_url": "https://cerberus.example",
        "request": {
            "repo": "misty-step/cerberus",
            "pr_number": 459,
            "head_sha": "abc123def456",
            "model": "fake/model",
            "github_token_present": true
        },
        "settings": {
            "timeout_seconds": 600,
            "poll_interval_seconds": 5,
            "max_poll_errors": 10,
            "fail_on_verdict": false,
            "write_verdict_json": true
        },
        "post": {
            "http_status": 202,
            "body": { "review_id": "review-459" }
        },
        "polls": [
            {
                "http_status": 200,
                "body": {
                    "status": "completed",
                    "aggregated_verdict": { "verdict": artifact.verdict },
                    "review_run_artifact": artifact
                }
            }
        ]
    })
    .to_string()
}

fn assert_no_review_artifact_key(value: &Value) {
    match value {
        Value::Object(fields) => {
            assert!(
                !fields.contains_key("review_run_artifact"),
                "review_run_artifact leaked into {value}"
            );
            for value in fields.values() {
                assert_no_review_artifact_key(value);
            }
        }
        Value::Array(values) => {
            for value in values {
                assert_no_review_artifact_key(value);
            }
        }
        _ => {}
    }
}
