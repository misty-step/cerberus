use serde_json::Value;
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
fn hosted_api_fixture_server_checks_auth_before_body_json() {
    let temp = temp_dir("auth-before-body");
    let mut server = FixtureServer::start(&temp, "service-store.json", 1);

    let response = request(&server.addr, "POST", "/api/reviews", None, Some("{"));

    assert_eq!(response.status, 401);
    assert_eq!(response.body["error"], "missing_or_invalid_auth");
    server.join();
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
