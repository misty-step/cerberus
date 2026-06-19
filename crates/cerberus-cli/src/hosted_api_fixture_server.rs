use anyhow::{bail, Context, Result};
use cerberus_adapter::{hosted_api_service_fixture_report, HostedApiServiceStoreFixture};
use serde_json::{json, Value};
use std::{
    fs,
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    path::{Path, PathBuf},
    time::Duration,
};

pub struct HostedApiFixtureServerConfig {
    pub addr: String,
    pub api_key: String,
    pub store: HostedApiServiceStoreFixture,
    pub store_state: Option<PathBuf>,
    pub max_requests: u64,
    pub ready_file: Option<PathBuf>,
}

pub fn run_hosted_api_fixture_server(mut config: HostedApiFixtureServerConfig) -> Result<()> {
    if config.max_requests == 0 {
        bail!("hosted-api-serve-fixture requires --max-requests greater than zero");
    }
    config
        .store
        .validate()
        .context("invalid hosted API fixture server store")?;

    let listener = TcpListener::bind(&config.addr)
        .with_context(|| format!("failed to bind hosted API fixture server {}", config.addr))?;
    let local_addr = listener.local_addr()?;
    if !local_addr.ip().is_loopback() {
        bail!("hosted-api-serve-fixture only supports loopback bind addresses");
    }
    if let Some(ready_file) = &config.ready_file {
        if let Some(parent) = ready_file
            .parent()
            .filter(|parent| !parent.as_os_str().is_empty())
        {
            fs::create_dir_all(parent)
                .with_context(|| format!("failed to create ready-file dir {}", parent.display()))?;
        }
        fs::write(ready_file, local_addr.to_string())
            .with_context(|| format!("failed to write ready file {}", ready_file.display()))?;
    }

    for _ in 0..config.max_requests {
        let (mut stream, _) = listener.accept().context("failed to accept HTTP request")?;
        handle_connection(
            &mut stream,
            &config.api_key,
            &mut config.store,
            config.store_state.as_deref(),
        )?;
    }

    Ok(())
}

fn handle_connection(
    stream: &mut TcpStream,
    api_key: &str,
    store: &mut HostedApiServiceStoreFixture,
    store_state: Option<&Path>,
) -> Result<()> {
    let request = match read_http_request(stream) {
        Ok(request) => request,
        Err(reason) => {
            write_json_response(
                stream,
                400,
                &json!({ "error": "bad_request", "reason": reason.to_string() }),
            )?;
            return Ok(());
        }
    };
    let auth_report = hosted_api_service_fixture_report(
        &request.method,
        &request.path,
        request.header("authorization"),
        api_key,
        None,
        store,
    );
    if auth_report.http_status == 401 {
        return write_json_response(stream, auth_report.http_status, &auth_report.body);
    }
    let body = match request.body_json() {
        Ok(body) => body,
        Err(reason) => {
            write_json_response(
                stream,
                400,
                &json!({ "error": "invalid_json", "reason": reason.to_string() }),
            )?;
            return Ok(());
        }
    };
    let report = hosted_api_service_fixture_report(
        &request.method,
        &request.path,
        request.header("authorization"),
        api_key,
        body.as_ref(),
        store,
    );
    if request.method.eq_ignore_ascii_case("POST") && report.http_status == 202 {
        if let (Some(dispatch), Some(store_state)) = (&report.dispatch_request, store_state) {
            let mut next_store = store.clone();
            if next_store.record_queued_review(dispatch).is_err()
                || write_store_state(store_state, &next_store).is_err()
            {
                return write_json_response(stream, 500, &json!({ "error": "store_error" }));
            }
            *store = next_store;
        }
    }
    write_json_response(stream, report.http_status, &report.body)
}

fn write_store_state(path: &Path, store: &HostedApiServiceStoreFixture) -> Result<()> {
    store.validate().context("invalid hosted API store state")?;
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        fs::create_dir_all(parent)
            .with_context(|| format!("failed to create store-state dir {}", parent.display()))?;
    }
    let raw = serde_json::to_string(store).context("failed to serialize hosted API store state")?;
    fs::write(path, raw)
        .with_context(|| format!("failed to write hosted API store state {}", path.display()))
}

struct HttpRequest {
    method: String,
    path: String,
    headers: Vec<(String, String)>,
    body: String,
}

impl HttpRequest {
    fn header(&self, name: &str) -> Option<&str> {
        self.headers
            .iter()
            .find(|(key, _)| key.eq_ignore_ascii_case(name))
            .map(|(_, value)| value.as_str())
    }

    fn body_json(&self) -> Result<Option<Value>> {
        if self.body.trim().is_empty() {
            return Ok(None);
        }
        serde_json::from_str(&self.body)
            .map(Some)
            .context("failed to parse HTTP request body as JSON")
    }
}

fn read_http_request(stream: &mut TcpStream) -> Result<HttpRequest> {
    stream
        .set_read_timeout(Some(Duration::from_secs(30)))
        .context("failed to set HTTP read timeout")?;
    let mut raw = Vec::new();
    let mut buf = [0; 1024];
    while !contains_header_end(&raw) {
        let read = stream
            .read(&mut buf)
            .context("failed to read HTTP request")?;
        if read == 0 {
            bail!("connection closed before HTTP headers");
        }
        raw.extend_from_slice(&buf[..read]);
        if raw.len() > 64 * 1024 {
            bail!("HTTP request headers exceeded 64KiB");
        }
    }

    let header_end = header_end(&raw).context("missing HTTP header terminator")?;
    let headers_text = std::str::from_utf8(&raw[..header_end])
        .context("HTTP request headers were not UTF-8")?
        .to_string();
    let content_length = content_length(&headers_text)?;
    while raw.len() < header_end + content_length {
        let read = stream
            .read(&mut buf)
            .context("failed to read HTTP request body")?;
        if read == 0 {
            bail!("connection closed before HTTP body was complete");
        }
        raw.extend_from_slice(&buf[..read]);
        if raw.len() > header_end + content_length {
            break;
        }
    }

    let mut lines = headers_text.lines();
    let request_line = lines.next().context("missing HTTP request line")?;
    let mut request_parts = request_line.split_whitespace();
    let method = request_parts
        .next()
        .context("missing HTTP request method")?
        .to_string();
    let path = request_parts
        .next()
        .context("missing HTTP request path")?
        .to_string();
    let headers = lines
        .filter_map(|line| {
            let (name, value) = line.split_once(':')?;
            Some((name.to_string(), value.trim().to_string()))
        })
        .collect();
    let body = String::from_utf8(raw[header_end..header_end + content_length].to_vec())
        .context("HTTP request body was not UTF-8")?;

    Ok(HttpRequest {
        method,
        path,
        headers,
        body,
    })
}

fn contains_header_end(raw: &[u8]) -> bool {
    raw.windows(4).any(|window| window == b"\r\n\r\n")
}

fn header_end(raw: &[u8]) -> Option<usize> {
    raw.windows(4)
        .position(|window| window == b"\r\n\r\n")
        .map(|position| position + 4)
}

fn content_length(headers_text: &str) -> Result<usize> {
    headers_text
        .lines()
        .find_map(|line| {
            let (name, value) = line.split_once(':')?;
            name.eq_ignore_ascii_case("content-length")
                .then(|| value.trim().parse::<usize>())
        })
        .transpose()
        .context("invalid HTTP Content-Length header")
        .map(|length| length.unwrap_or(0))
}

fn write_json_response(stream: &mut TcpStream, status: u16, body: &Value) -> Result<()> {
    let body = serde_json::to_string(body).context("failed to serialize HTTP response body")?;
    write!(
        stream,
        "HTTP/1.1 {} {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        status,
        reason_phrase(status),
        body.len(),
        body
    )
    .context("failed to write HTTP response")
}

fn reason_phrase(status: u16) -> &'static str {
    match status {
        200 => "OK",
        202 => "Accepted",
        400 => "Bad Request",
        401 => "Unauthorized",
        404 => "Not Found",
        422 => "Unprocessable Entity",
        500 => "Internal Server Error",
        _ => "OK",
    }
}
