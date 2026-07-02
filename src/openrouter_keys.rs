//! Scoped ephemeral OpenRouter key lifecycle (backlog 013 M1).
//!
//! Cerberus previously forwarded the operator's long-lived `OPENROUTER_API_KEY`
//! straight into an untrusted review substrate that also has webfetch/bash
//! access — a confirmed exfil path for prompt-injected agents. This module
//! mints a per-review key capped at a USD limit via OpenRouter's provisioning
//! API, hands the caller a crash-safe guard that revokes it, and sweeps orphan
//! keys left by crashed runs. A stolen key is worth at most its cap for the
//! brief window before revocation, not the operator's real balance.

use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::{anyhow, Context, Result};
use serde::Deserialize;
use serde_json::Value;

/// Default OpenRouter API base URL. Tests point `ProvisioningClient` at a
/// local mock server instead.
pub const DEFAULT_BASE_URL: &str = "https://openrouter.ai/api/v1";

/// Every key Cerberus mints for a review carries this name prefix so the
/// orphan sweeper can find review-tagged keys (and only those) without
/// touching unrelated keys on the same provisioning account.
pub const REVIEW_KEY_NAME_PREFIX: &str = "cerberus-review-";

/// A minted, usable key. `secret` is the plaintext value OpenRouter returns
/// exactly once, at creation; it is never retrievable again after this call
/// returns, so callers must inject it into the child process immediately.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MintedKey {
    pub hash: String,
    pub secret: String,
    pub name: String,
}

/// A key as returned by list/create, without the plaintext secret.
#[derive(Debug, Clone, Deserialize)]
pub struct KeyRecord {
    pub hash: String,
    pub name: String,
    #[serde(default)]
    pub disabled: bool,
}

/// Client for OpenRouter's key-provisioning (management) API. The
/// provisioning key stays host-side and never enters the review substrate —
/// it is secret-zero, distinct from the scoped keys it mints.
#[derive(Debug, Clone)]
pub struct ProvisioningClient {
    base_url: String,
    provisioning_key: String,
}

impl ProvisioningClient {
    pub fn new(provisioning_key: impl Into<String>) -> Self {
        Self {
            base_url: DEFAULT_BASE_URL.to_string(),
            provisioning_key: provisioning_key.into(),
        }
    }

    #[cfg(test)]
    fn with_base_url(provisioning_key: impl Into<String>, base_url: impl Into<String>) -> Self {
        Self {
            base_url: base_url.into(),
            provisioning_key: provisioning_key.into(),
        }
    }

    fn auth_header(&self) -> String {
        format!("Bearer {}", self.provisioning_key)
    }

    /// Mint a new key named `name`, capped at `limit_usd`. The name should
    /// carry [`REVIEW_KEY_NAME_PREFIX`] so the orphan sweeper can find it.
    pub fn mint_key(&self, name: &str, limit_usd: f64) -> Result<MintedKey> {
        let url = format!("{}/keys", self.base_url);
        let body = serde_json::json!({ "name": name, "limit": limit_usd });
        let mut response = ureq::post(&url)
            .header("Authorization", self.auth_header())
            .header("Content-Type", "application/json")
            .send_json(&body)
            .with_context(|| format!("mint scoped OpenRouter key {name:?}"))?;
        let payload: Value = response
            .body_mut()
            .read_json()
            .context("parse OpenRouter mint-key response")?;
        let secret = payload
            .get("key")
            .and_then(Value::as_str)
            .ok_or_else(|| anyhow!("OpenRouter mint-key response missing plaintext \"key\""))?
            .to_string();
        let hash = payload
            .get("data")
            .and_then(|data| data.get("hash"))
            .and_then(Value::as_str)
            .ok_or_else(|| anyhow!("OpenRouter mint-key response missing \"data.hash\""))?
            .to_string();
        Ok(MintedKey {
            hash,
            secret,
            name: name.to_string(),
        })
    }

    /// Revoke (delete) a key by hash. Idempotent: a key already gone (404)
    /// counts as success, since the goal — the key being unusable — already
    /// holds.
    pub fn revoke_key(&self, hash: &str) -> Result<()> {
        let url = format!("{}/keys/{hash}", self.base_url);
        match ureq::delete(&url)
            .header("Authorization", self.auth_header())
            .call()
        {
            Ok(_) => Ok(()),
            Err(ureq::Error::StatusCode(404)) => Ok(()),
            Err(err) => Err(err).with_context(|| format!("revoke OpenRouter key {hash}")),
        }
    }

    /// List keys visible to this provisioning key (most recent page only;
    /// the sweeper does not need to paginate through history).
    pub fn list_keys(&self) -> Result<Vec<KeyRecord>> {
        let url = format!("{}/keys", self.base_url);
        let mut response = ureq::get(&url)
            .header("Authorization", self.auth_header())
            .call()
            .context("list OpenRouter keys")?;
        let payload: Value = response
            .body_mut()
            .read_json()
            .context("parse OpenRouter list-keys response")?;
        let entries = payload
            .get("data")
            .and_then(Value::as_array)
            .ok_or_else(|| anyhow!("OpenRouter list-keys response missing \"data\" array"))?;
        entries
            .iter()
            .map(|entry| {
                serde_json::from_value(entry.clone()).context("parse OpenRouter key record")
            })
            .collect()
    }
}

/// A minted key plus the means to revoke it. `revoke` gives the happy path a
/// real `Result`; `Drop` is the crash-safety net for a panic or an early `?`
/// return, so a review that errors out still tears down its key. Drop cannot
/// survive a SIGKILL or host crash — that residual is what
/// [`sweep_orphaned_keys`] cleans up on the next run.
pub struct ScopedKeyGuard<'a> {
    client: &'a ProvisioningClient,
    hash: String,
    revoked: bool,
}

impl<'a> ScopedKeyGuard<'a> {
    pub fn new(client: &'a ProvisioningClient, hash: impl Into<String>) -> Self {
        Self {
            client,
            hash: hash.into(),
            revoked: false,
        }
    }

    pub fn hash(&self) -> &str {
        &self.hash
    }

    /// Revoke now and consume the guard. On success, `Drop` becomes a no-op.
    /// On failure, `self.revoked` is still `false` when this function
    /// returns via `?`, so the guard's `Drop` retries the revoke once as it
    /// unwinds.
    pub fn revoke(mut self) -> Result<()> {
        self.client.revoke_key(&self.hash)?;
        self.revoked = true;
        Ok(())
    }
}

impl Drop for ScopedKeyGuard<'_> {
    fn drop(&mut self) {
        if self.revoked {
            return;
        }
        if let Err(err) = self.client.revoke_key(&self.hash) {
            eprintln!(
                "cerberus: crash-safety revoke of scoped OpenRouter key {} failed: {err:#}; \
                 the orphan sweeper will retry it on the next run",
                self.hash
            );
        }
    }
}

/// Build a review-key name embedding the mint time so the sweeper can read
/// age straight back out of the name without depending on the provisioning
/// API's timestamp format: `cerberus-review-<unix-seconds>-<tag>`.
pub fn scoped_key_name(tag: &str, minted_at: SystemTime) -> String {
    let unix_seconds = minted_at
        .duration_since(UNIX_EPOCH)
        .unwrap_or(Duration::ZERO)
        .as_secs();
    format!("{REVIEW_KEY_NAME_PREFIX}{unix_seconds}-{tag}")
}

fn key_age(name: &str, now: SystemTime) -> Option<Duration> {
    let suffix = name.strip_prefix(REVIEW_KEY_NAME_PREFIX)?;
    let unix_seconds: u64 = suffix.split('-').next()?.parse().ok()?;
    let minted_at = UNIX_EPOCH + Duration::from_secs(unix_seconds);
    now.duration_since(minted_at).ok()
}

/// Revoke review-tagged keys older than `max_age` — the crash-safety net for
/// runs killed before their own [`ScopedKeyGuard`] could fire. Best-effort:
/// a single key's revoke failure does not stop the sweep of the rest; the
/// full list of hashes this call revoked is returned so callers can log it.
pub fn sweep_orphaned_keys(client: &ProvisioningClient, max_age: Duration) -> Result<Vec<String>> {
    sweep_orphaned_keys_at(client, max_age, SystemTime::now())
}

fn sweep_orphaned_keys_at(
    client: &ProvisioningClient,
    max_age: Duration,
    now: SystemTime,
) -> Result<Vec<String>> {
    let keys = client.list_keys().context("list keys for orphan sweep")?;
    let mut revoked = Vec::new();
    for key in keys {
        if key.disabled {
            continue;
        }
        let Some(age) = key_age(&key.name, now) else {
            continue;
        };
        if age < max_age {
            continue;
        }
        if let Err(err) = client.revoke_key(&key.hash) {
            eprintln!(
                "cerberus: orphan sweep failed to revoke stale scoped OpenRouter key {} ({}): {err:#}",
                key.hash, key.name
            );
            continue;
        }
        revoked.push(key.hash);
    }
    Ok(revoked)
}

/// Sweep orphaned review keys left by a crashed prior run (best-effort,
/// logged not fatal), then mint a fresh one tagged `tag` and capped at
/// `limit_usd`. This is the whole M1 lifecycle entry point a caller needs:
/// mint returns the plaintext secret to inject immediately, and the caller is
/// responsible for wrapping the returned hash in a [`ScopedKeyGuard`] so it
/// gets revoked when the review is done with it.
pub fn mint_review_key(
    client: &ProvisioningClient,
    tag: &str,
    limit_usd: f64,
    orphan_sweep_age: Duration,
) -> Result<MintedKey> {
    match sweep_orphaned_keys(client, orphan_sweep_age) {
        Ok(revoked) if !revoked.is_empty() => eprintln!(
            "cerberus: orphan sweep revoked {} stale scoped OpenRouter key(s) from a prior run",
            revoked.len()
        ),
        Ok(_) => {}
        Err(err) => eprintln!(
            "cerberus: orphan sweep for scoped OpenRouter keys failed (continuing): {err:#}"
        ),
    }
    let name = scoped_key_name(tag, SystemTime::now());
    client.mint_key(&name, limit_usd)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{BufRead, BufReader, Read, Write};
    use std::net::{TcpListener, TcpStream};
    use std::thread;

    struct RecordedRequest {
        method: String,
        path: String,
        authorization: Option<String>,
        body: String,
    }

    /// One-shot-per-request mock server: each entry in `responses` is served
    /// to one accepted connection, in order, on a background thread. The
    /// returned join handle yields every request it actually observed, so
    /// tests can assert on method/path/headers/body without a mocking crate.
    fn spawn_mock_server(
        responses: Vec<(u16, String)>,
    ) -> (String, thread::JoinHandle<Vec<RecordedRequest>>) {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind mock server");
        let addr = listener.local_addr().expect("mock server addr");
        let handle = thread::spawn(move || {
            let mut recorded = Vec::new();
            for (status, body) in responses {
                let (stream, _) = listener.accept().expect("accept mock connection");
                recorded.push(handle_one_request(stream, status, &body));
            }
            recorded
        });
        (format!("http://{addr}"), handle)
    }

    fn handle_one_request(mut stream: TcpStream, status: u16, body: &str) -> RecordedRequest {
        let read_half = stream.try_clone().expect("clone mock stream for reading");
        let mut reader = BufReader::new(read_half);

        let mut request_line = String::new();
        reader
            .read_line(&mut request_line)
            .expect("read request line");
        let mut parts = request_line.split_whitespace();
        let method = parts.next().unwrap_or_default().to_string();
        let path = parts.next().unwrap_or_default().to_string();

        let mut authorization = None;
        let mut content_length = 0usize;
        loop {
            let mut line = String::new();
            reader.read_line(&mut line).expect("read header line");
            let trimmed = line.trim_end_matches(['\r', '\n']);
            if trimmed.is_empty() {
                break;
            }
            if let Some(idx) = trimmed.find(':') {
                let (name, value) = trimmed.split_at(idx);
                let value = value[1..].trim().to_string();
                match name.to_ascii_lowercase().as_str() {
                    "authorization" => authorization = Some(value),
                    "content-length" => content_length = value.parse().unwrap_or(0),
                    _ => {}
                }
            }
        }
        let mut body_buf = vec![0u8; content_length];
        if content_length > 0 {
            reader.read_exact(&mut body_buf).expect("read request body");
        }

        let response = format!(
            "HTTP/1.1 {status} status\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            body.len(),
            body
        );
        stream
            .write_all(response.as_bytes())
            .expect("write mock response");
        stream.flush().ok();

        RecordedRequest {
            method,
            path,
            authorization,
            body: String::from_utf8_lossy(&body_buf).into_owned(),
        }
    }

    #[test]
    fn mint_key_parses_secret_and_hash_and_sends_bearer_auth() {
        let (base_url, handle) = spawn_mock_server(vec![(
            201,
            serde_json::json!({
                "key": "sk-or-v1-stolen-worthless",
                "data": {
                    "hash": "hash-123",
                    "name": "cerberus-review-1-abc",
                    "label": "sk-or-v1-a...c",
                    "disabled": false,
                    "limit": 5.0
                }
            })
            .to_string(),
        )]);
        let client = ProvisioningClient::with_base_url("mgmt-key", base_url);

        let minted = client
            .mint_key("cerberus-review-1-abc", 5.0)
            .expect("mint key");

        assert_eq!(minted.hash, "hash-123");
        assert_eq!(minted.secret, "sk-or-v1-stolen-worthless");
        assert_eq!(minted.name, "cerberus-review-1-abc");

        let requests = handle.join().expect("mock server thread");
        assert_eq!(requests.len(), 1);
        assert_eq!(requests[0].method, "POST");
        assert_eq!(requests[0].path, "/keys");
        assert_eq!(
            requests[0].authorization.as_deref(),
            Some("Bearer mgmt-key")
        );
        let sent: Value = serde_json::from_str(&requests[0].body).expect("sent body is json");
        assert_eq!(sent["name"], "cerberus-review-1-abc");
        assert_eq!(sent["limit"], 5.0);
    }

    #[test]
    fn revoke_key_sends_delete_to_hash_path() {
        let (base_url, handle) = spawn_mock_server(vec![(200, "{}".to_string())]);
        let client = ProvisioningClient::with_base_url("mgmt-key", base_url);

        client.revoke_key("hash-123").expect("revoke succeeds");

        let requests = handle.join().expect("mock server thread");
        assert_eq!(requests[0].method, "DELETE");
        assert_eq!(requests[0].path, "/keys/hash-123");
        assert_eq!(
            requests[0].authorization.as_deref(),
            Some("Bearer mgmt-key")
        );
    }

    #[test]
    fn revoke_key_treats_404_as_already_gone_success() {
        let (base_url, handle) = spawn_mock_server(vec![(404, "{}".to_string())]);
        let client = ProvisioningClient::with_base_url("mgmt-key", base_url);

        client
            .revoke_key("already-deleted")
            .expect("404 on revoke is idempotent success, not an error");

        handle.join().expect("mock server thread");
    }

    #[test]
    fn revoke_key_propagates_non_404_failure() {
        let (base_url, handle) = spawn_mock_server(vec![(500, "{}".to_string())]);
        let client = ProvisioningClient::with_base_url("mgmt-key", base_url);

        let err = client.revoke_key("hash-500").unwrap_err();
        assert!(err.to_string().contains("revoke OpenRouter key hash-500"));

        handle.join().expect("mock server thread");
    }

    #[test]
    fn list_keys_parses_data_array() {
        let (base_url, handle) = spawn_mock_server(vec![(
            200,
            serde_json::json!({
                "data": [
                    {"hash": "h1", "name": "cerberus-review-1-a", "disabled": false},
                    {"hash": "h2", "name": "unrelated-key", "disabled": true},
                ]
            })
            .to_string(),
        )]);
        let client = ProvisioningClient::with_base_url("mgmt-key", base_url);

        let keys = client.list_keys().expect("list keys");

        assert_eq!(keys.len(), 2);
        assert_eq!(keys[0].hash, "h1");
        assert!(!keys[0].disabled);
        assert_eq!(keys[1].hash, "h2");
        assert!(keys[1].disabled);

        handle.join().expect("mock server thread");
    }

    #[test]
    fn guard_drop_revokes_exactly_once_when_not_explicitly_revoked() {
        let (base_url, handle) = spawn_mock_server(vec![(200, "{}".to_string())]);
        let client = ProvisioningClient::with_base_url("mgmt-key", base_url);

        {
            let _guard = ScopedKeyGuard::new(&client, "hash-drop");
        }

        let requests = handle.join().expect("mock server thread");
        assert_eq!(requests.len(), 1, "drop should revoke exactly once");
        assert_eq!(requests[0].method, "DELETE");
        assert_eq!(requests[0].path, "/keys/hash-drop");
    }

    #[test]
    fn explicit_revoke_prevents_drop_from_revoking_again() {
        let (base_url, handle) = spawn_mock_server(vec![(200, "{}".to_string())]);
        let client = ProvisioningClient::with_base_url("mgmt-key", base_url);

        let guard = ScopedKeyGuard::new(&client, "hash-explicit");
        guard.revoke().expect("explicit revoke succeeds");

        let requests = handle.join().expect("mock server thread");
        assert_eq!(
            requests.len(),
            1,
            "explicit revoke should mark the guard revoked so drop is a no-op"
        );
    }

    #[test]
    fn scoped_key_name_round_trips_through_key_age() {
        let minted_at = UNIX_EPOCH + Duration::from_secs(1_000_000);
        let name = scoped_key_name("abc123", minted_at);
        assert!(name.starts_with(REVIEW_KEY_NAME_PREFIX));

        let now = minted_at + Duration::from_secs(90);
        let age = key_age(&name, now).expect("age parses back out of the name");
        assert_eq!(age, Duration::from_secs(90));
    }

    #[test]
    fn key_age_ignores_names_without_the_review_prefix() {
        assert!(key_age("some-other-key", SystemTime::now()).is_none());
    }

    #[test]
    fn sweep_revokes_only_review_tagged_keys_older_than_max_age() {
        let now = UNIX_EPOCH + Duration::from_secs(2_000_000);
        let stale = scoped_key_name("stale", now - Duration::from_secs(3600));
        let fresh = scoped_key_name("fresh", now - Duration::from_secs(5));
        let (base_url, handle) = spawn_mock_server(vec![
            (
                200,
                serde_json::json!({
                    "data": [
                        {"hash": "h-stale", "name": stale, "disabled": false},
                        {"hash": "h-fresh", "name": fresh, "disabled": false},
                        {"hash": "h-unrelated", "name": "some-other-app-key", "disabled": false},
                        {"hash": "h-already-disabled", "name": scoped_key_name("dead", now - Duration::from_secs(9999)), "disabled": true},
                    ]
                })
                .to_string(),
            ),
            (200, "{}".to_string()), // revoke of h-stale
        ]);
        let client = ProvisioningClient::with_base_url("mgmt-key", base_url);

        let revoked = sweep_orphaned_keys_at(&client, Duration::from_secs(1800), now)
            .expect("sweep succeeds");

        assert_eq!(revoked, vec!["h-stale".to_string()]);

        let requests = handle.join().expect("mock server thread");
        assert_eq!(requests.len(), 2);
        assert_eq!(requests[0].method, "GET");
        assert_eq!(requests[1].method, "DELETE");
        assert_eq!(requests[1].path, "/keys/h-stale");
    }

    #[test]
    fn sweep_continues_past_a_single_revoke_failure() {
        let now = UNIX_EPOCH + Duration::from_secs(2_000_000);
        let stale_a = scoped_key_name("a", now - Duration::from_secs(3600));
        let stale_b = scoped_key_name("b", now - Duration::from_secs(3600));
        let (base_url, handle) = spawn_mock_server(vec![
            (
                200,
                serde_json::json!({
                    "data": [
                        {"hash": "h-a", "name": stale_a, "disabled": false},
                        {"hash": "h-b", "name": stale_b, "disabled": false},
                    ]
                })
                .to_string(),
            ),
            (500, "{}".to_string()), // revoke of h-a fails
            (200, "{}".to_string()), // revoke of h-b still attempted
        ]);
        let client = ProvisioningClient::with_base_url("mgmt-key", base_url);

        let revoked = sweep_orphaned_keys_at(&client, Duration::from_secs(1800), now)
            .expect("sweep succeeds despite one failure");

        assert_eq!(revoked, vec!["h-b".to_string()]);

        handle.join().expect("mock server thread");
    }

    #[test]
    fn mint_review_key_sweeps_before_minting_and_tags_the_new_key() {
        let (base_url, handle) = spawn_mock_server(vec![
            (200, serde_json::json!({ "data": [] }).to_string()), // sweep: nothing stale
            (
                201,
                serde_json::json!({
                    "key": "sk-or-v1-fresh",
                    "data": { "hash": "hash-fresh", "name": "irrelevant", "disabled": false }
                })
                .to_string(),
            ),
        ]);
        let client = ProvisioningClient::with_base_url("mgmt-key", base_url);

        let minted = mint_review_key(&client, "review-42", 5.0, Duration::from_secs(1800))
            .expect("sweep then mint succeeds");

        assert_eq!(minted.secret, "sk-or-v1-fresh");
        assert_eq!(minted.hash, "hash-fresh");
        assert!(
            minted.name.starts_with(REVIEW_KEY_NAME_PREFIX) && minted.name.ends_with("review-42"),
            "minted key name should carry the review prefix and tag: {}",
            minted.name
        );

        let requests = handle.join().expect("mock server thread");
        assert_eq!(requests.len(), 2, "sweep (list) must run before mint");
        assert_eq!(requests[0].method, "GET");
        assert_eq!(requests[1].method, "POST");
    }

    #[test]
    fn mint_review_key_still_mints_when_the_sweep_itself_fails() {
        let (base_url, handle) = spawn_mock_server(vec![
            (500, "{}".to_string()), // sweep's list call fails
            (
                201,
                serde_json::json!({
                    "key": "sk-or-v1-fresh",
                    "data": { "hash": "hash-fresh", "name": "irrelevant", "disabled": false }
                })
                .to_string(),
            ),
        ]);
        let client = ProvisioningClient::with_base_url("mgmt-key", base_url);

        let minted = mint_review_key(&client, "review-42", 5.0, Duration::from_secs(1800))
            .expect("a broken sweep must not block minting a usable key");

        assert_eq!(minted.secret, "sk-or-v1-fresh");

        handle.join().expect("mock server thread");
    }
}
