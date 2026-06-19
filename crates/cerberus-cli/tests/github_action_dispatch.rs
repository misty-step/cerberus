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

fn response(status: u16, body: &'static str) -> FakeResponse {
    FakeResponse { status, body }
}

struct FakeResponse {
    status: u16,
    body: &'static str,
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
