use crate::AdapterError;
use cerberus_schema::{ReviewRunArtifact, Verdict};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::{BTreeMap, VecDeque};

pub const HOSTED_API_INGRESS_FIXTURE_REPORT_VERSION: &str = "hosted-api-ingress-fixture-report.v1";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct HostedApiDispatchRequest {
    pub repo: String,
    pub pr_number: u64,
    pub head_sha: String,
    #[serde(default)]
    pub model: String,
    #[serde(default)]
    pub github_token_present: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct HostedApiIngressFixtureReport {
    pub schema_version: String,
    pub http_status: u16,
    pub body: Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub dispatch_request: Option<HostedApiDispatchRequest>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct HostedApiDispatchSettings {
    pub timeout_seconds: u64,
    pub poll_interval_seconds: u64,
    #[serde(default = "default_max_poll_errors")]
    pub max_poll_errors: u64,
    #[serde(default = "default_fail_on_verdict")]
    pub fail_on_verdict: bool,
    #[serde(default)]
    pub write_verdict_json: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HostedApiDispatchConfig {
    pub api_base_url: String,
    pub api_key: String,
    pub github_token: Option<String>,
    pub request: HostedApiDispatchRequest,
    pub settings: HostedApiDispatchSettings,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct HostedApiHttpResponse {
    pub http_status: u16,
    #[serde(default)]
    pub body: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct HostedApiDispatchTranscript {
    pub api_base_url: String,
    pub request: HostedApiDispatchRequest,
    pub settings: HostedApiDispatchSettings,
    pub post: HostedApiHttpResponse,
    #[serde(default)]
    pub polls: Vec<HostedApiHttpResponse>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum HostedApiDispatchOutcome {
    Completed,
    DispatchRejected,
    InvalidDispatchResponse,
    ReviewFailed,
    PollErrorsExhausted,
    TimedOut,
    TranscriptExhausted,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct HostedApiDispatchDecision {
    pub outcome: HostedApiDispatchOutcome,
    pub exit_code: i32,
    pub review_id: String,
    pub verdict: String,
    pub github_outputs: BTreeMap<String, String>,
    pub elapsed_seconds: u64,
    pub poll_attempts: u64,
    pub consecutive_poll_errors: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub verdict_json: Option<Value>,
    #[serde(skip)]
    pub review_run_artifact: Option<ReviewRunArtifact>,
    #[serde(skip)]
    pub review_run_artifact_error: Option<String>,
    pub messages: Vec<String>,
}

pub trait HostedApiDispatchTransport {
    fn post_review(
        &mut self,
        config: &HostedApiDispatchConfig,
    ) -> Result<HostedApiHttpResponse, String>;

    fn poll_review(
        &mut self,
        config: &HostedApiDispatchConfig,
        review_id: &str,
    ) -> Result<Option<HostedApiHttpResponse>, String>;

    fn sleep(&mut self, seconds: u64);
}

pub fn run_hosted_api_dispatch_fixture(
    transcript: &HostedApiDispatchTranscript,
) -> Result<HostedApiDispatchDecision, AdapterError> {
    let mut transport = TranscriptHostedApiTransport {
        post: Some(transcript.post.clone()),
        polls: transcript.polls.clone().into(),
    };
    let config = HostedApiDispatchConfig {
        api_base_url: transcript.api_base_url.clone(),
        api_key: "fixture-api-key".to_string(),
        github_token: None,
        request: transcript.request.clone(),
        settings: transcript.settings.clone(),
    };
    run_hosted_api_dispatch(&config, &mut transport)
}

pub fn hosted_api_ingress_fixture_report(
    body: &Value,
    review_id: u64,
) -> HostedApiIngressFixtureReport {
    match parse_hosted_api_review_submission(body) {
        Ok(submission) => HostedApiIngressFixtureReport {
            schema_version: HOSTED_API_INGRESS_FIXTURE_REPORT_VERSION.to_string(),
            http_status: 202,
            body: json!({
                "review_id": review_id,
                "status": "queued"
            }),
            dispatch_request: Some(submission.into_dispatch_request()),
        },
        Err(reason) => HostedApiIngressFixtureReport {
            schema_version: HOSTED_API_INGRESS_FIXTURE_REPORT_VERSION.to_string(),
            http_status: 422,
            body: json!({ "error": reason }),
            dispatch_request: None,
        },
    }
}

pub fn run_hosted_api_dispatch(
    config: &HostedApiDispatchConfig,
    transport: &mut impl HostedApiDispatchTransport,
) -> Result<HostedApiDispatchDecision, AdapterError> {
    validate_config(config)?;
    let mut messages = Vec::new();

    let post = match transport.post_review(config) {
        Ok(response) => response,
        Err(reason) => {
            messages.push(format!("dispatch POST transport error: {reason}"));
            return Ok(decision(
                HostedApiDispatchOutcome::DispatchRejected,
                1,
                "",
                "SKIP",
                0,
                0,
                0,
                None,
                messages,
            ));
        }
    };

    if post.http_status != 202 {
        messages.push(format!(
            "dispatch POST returned HTTP {}, expected 202",
            post.http_status
        ));
        return Ok(decision(
            HostedApiDispatchOutcome::DispatchRejected,
            1,
            "",
            "SKIP",
            0,
            0,
            0,
            None,
            messages,
        ));
    }

    let Some(review_id) = review_id_field(&post.body) else {
        messages.push("dispatch POST response did not include review_id".to_string());
        return Ok(decision(
            HostedApiDispatchOutcome::InvalidDispatchResponse,
            1,
            "",
            "SKIP",
            0,
            0,
            0,
            None,
            messages,
        ));
    };
    if !is_safe_github_output_value(&review_id) {
        messages.push("dispatch POST response included unsafe review_id".to_string());
        return Ok(decision(
            HostedApiDispatchOutcome::InvalidDispatchResponse,
            1,
            "",
            Verdict::Skip.as_str(),
            0,
            0,
            0,
            None,
            messages,
        ));
    }

    let mut elapsed_seconds = 0;
    let mut poll_attempts = 0;
    let mut consecutive_poll_errors = 0;

    while elapsed_seconds < config.settings.timeout_seconds {
        transport.sleep(config.settings.poll_interval_seconds);
        elapsed_seconds += config.settings.poll_interval_seconds;
        poll_attempts += 1;

        let Some(poll) = (match transport.poll_review(config, &review_id) {
            Ok(response) => response,
            Err(reason) => {
                consecutive_poll_errors += 1;
                messages.push(format!(
                    "poll attempt {poll_attempts} transport error: {reason}"
                ));
                if consecutive_poll_errors >= config.settings.max_poll_errors {
                    messages.push(format!(
                        "polling stopped after {consecutive_poll_errors} consecutive HTTP errors"
                    ));
                    return Ok(decision(
                        HostedApiDispatchOutcome::PollErrorsExhausted,
                        1,
                        &review_id,
                        "SKIP",
                        elapsed_seconds,
                        poll_attempts,
                        consecutive_poll_errors,
                        None,
                        messages,
                    ));
                }
                continue;
            }
        }) else {
            messages.push(format!(
                "transcript ended before review {review_id} reached a terminal status"
            ));
            return Ok(decision(
                HostedApiDispatchOutcome::TranscriptExhausted,
                1,
                &review_id,
                "SKIP",
                elapsed_seconds,
                poll_attempts,
                consecutive_poll_errors,
                None,
                messages,
            ));
        };

        if poll.http_status != 200 {
            consecutive_poll_errors += 1;
            messages.push(format!(
                "poll attempt {poll_attempts} returned HTTP {}",
                poll.http_status
            ));
            if consecutive_poll_errors >= config.settings.max_poll_errors {
                messages.push(format!(
                    "polling stopped after {consecutive_poll_errors} consecutive HTTP errors"
                ));
                return Ok(decision(
                    HostedApiDispatchOutcome::PollErrorsExhausted,
                    1,
                    &review_id,
                    "SKIP",
                    elapsed_seconds,
                    poll_attempts,
                    consecutive_poll_errors,
                    None,
                    messages,
                ));
            }
            continue;
        }

        consecutive_poll_errors = 0;
        match string_field(&poll.body, "status") {
            Some("queued" | "running") => {}
            Some("failed") => {
                messages.push(format!("review {review_id} failed in hosted API"));
                return Ok(decision(
                    HostedApiDispatchOutcome::ReviewFailed,
                    1,
                    &review_id,
                    "SKIP",
                    elapsed_seconds,
                    poll_attempts,
                    consecutive_poll_errors,
                    None,
                    messages,
                ));
            }
            Some("completed") => {
                let verdict = match completed_verdict(&poll.body) {
                    Ok(verdict) => verdict,
                    Err(reason) => {
                        messages.push(reason);
                        return Ok(decision(
                            HostedApiDispatchOutcome::InvalidDispatchResponse,
                            1,
                            &review_id,
                            Verdict::Skip.as_str(),
                            elapsed_seconds,
                            poll_attempts,
                            consecutive_poll_errors,
                            None,
                            messages,
                        ));
                    }
                };
                let review_run_artifact = match completed_review_artifact(
                    &poll.body,
                    verdict,
                    &config.request.head_sha,
                ) {
                    Ok(artifact) => artifact,
                    Err(reason) => {
                        messages.push(reason.clone());
                        let mut rejected_artifact = decision(
                            HostedApiDispatchOutcome::InvalidDispatchResponse,
                            1,
                            &review_id,
                            Verdict::Skip.as_str(),
                            elapsed_seconds,
                            poll_attempts,
                            consecutive_poll_errors,
                            None,
                            messages,
                        );
                        rejected_artifact.review_run_artifact_error = Some(reason);
                        return Ok(rejected_artifact);
                    }
                };
                let exit_code = i32::from(config.settings.fail_on_verdict && verdict == "FAIL");
                if exit_code != 0 {
                    messages.push("fail-on-verdict converted FAIL verdict to exit 1".to_string());
                }
                let verdict_json = config
                    .settings
                    .write_verdict_json
                    .then(|| verdict_json_body(&poll.body));
                let mut completed = decision(
                    HostedApiDispatchOutcome::Completed,
                    exit_code,
                    &review_id,
                    &verdict,
                    elapsed_seconds,
                    poll_attempts,
                    consecutive_poll_errors,
                    verdict_json,
                    messages,
                );
                completed.review_run_artifact = review_run_artifact;
                return Ok(completed);
            }
            Some(status) => {
                messages.push(format!(
                    "poll attempt {poll_attempts} returned unknown status {status:?}"
                ));
            }
            None => {
                messages.push(format!(
                    "poll attempt {poll_attempts} response did not include status"
                ));
            }
        }
    }

    messages.push(format!(
        "timed out after {elapsed_seconds}s while waiting for review {review_id}"
    ));
    Ok(decision(
        HostedApiDispatchOutcome::TimedOut,
        1,
        &review_id,
        "SKIP",
        elapsed_seconds,
        poll_attempts,
        consecutive_poll_errors,
        None,
        messages,
    ))
}

fn default_max_poll_errors() -> u64 {
    10
}

fn default_fail_on_verdict() -> bool {
    true
}

fn validate_config(config: &HostedApiDispatchConfig) -> Result<(), AdapterError> {
    non_empty("api_base_url", &config.api_base_url)?;
    non_empty("api_key", &config.api_key)?;
    non_empty("request.repo", &config.request.repo)?;
    if config.request.pr_number == 0 {
        return invalid("request.pr_number must be greater than zero");
    }
    non_empty("request.head_sha", &config.request.head_sha)?;
    if config.settings.poll_interval_seconds == 0 {
        return invalid("settings.poll_interval_seconds must be greater than zero");
    }
    if config.settings.max_poll_errors == 0 {
        return invalid("settings.max_poll_errors must be greater than zero");
    }
    Ok(())
}

fn non_empty(field: &'static str, value: &str) -> Result<(), AdapterError> {
    if value.trim().is_empty() {
        return invalid(format!("{field} must not be empty"));
    }
    Ok(())
}

fn invalid(reason: impl Into<String>) -> Result<(), AdapterError> {
    Err(AdapterError::HostedApiDispatchTranscript {
        reason: reason.into(),
    })
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct HostedApiReviewSubmission {
    repo: String,
    pr_number: u64,
    head_sha: String,
    model: String,
    github_token_present: bool,
}

impl HostedApiReviewSubmission {
    fn into_dispatch_request(self) -> HostedApiDispatchRequest {
        HostedApiDispatchRequest {
            repo: self.repo,
            pr_number: self.pr_number,
            head_sha: self.head_sha,
            model: self.model,
            github_token_present: self.github_token_present,
        }
    }
}

fn parse_hosted_api_review_submission(body: &Value) -> Result<HostedApiReviewSubmission, String> {
    let repo = required_string(body, "repo", "missing required field: repo")?;
    let pr_number = match body.get("pr_number").and_then(Value::as_u64) {
        Some(pr_number) => pr_number,
        None => return Err("missing or invalid field: pr_number (must be integer)".to_string()),
    };
    let head_sha = required_string(body, "head_sha", "missing required field: head_sha")?;
    let github_token = normalize_optional_string(body.get("github_token"));
    if github_token
        .as_deref()
        .is_some_and(|value| value.contains(['\r', '\n']))
    {
        return Err("invalid field: github_token".to_string());
    }

    Ok(HostedApiReviewSubmission {
        repo,
        pr_number,
        head_sha,
        model: body
            .get("model")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        github_token_present: github_token.is_some(),
    })
}

fn required_string(body: &Value, field: &str, error: &str) -> Result<String, String> {
    match body.get(field).and_then(Value::as_str) {
        Some(value) if !value.is_empty() => Ok(value.to_string()),
        _ => Err(error.to_string()),
    }
}

fn normalize_optional_string(value: Option<&Value>) -> Option<String> {
    value
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn review_id_field(body: &Value) -> Option<String> {
    match body.get("review_id")? {
        Value::String(value) => {
            let trimmed = value.trim();
            (!trimmed.is_empty()).then(|| trimmed.to_string())
        }
        Value::Number(number) => number.as_u64().map(|value| value.to_string()),
        _ => None,
    }
}

fn string_field<'a>(body: &'a Value, field: &str) -> Option<&'a str> {
    body.get(field)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
}

fn completed_verdict(body: &Value) -> Result<&'static str, String> {
    let Some(raw) = body
        .get("aggregated_verdict")
        .and_then(|value| value.get("verdict"))
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
    else {
        return Ok(Verdict::Skip.as_str());
    };

    match raw {
        "PASS" => Ok(Verdict::Pass.as_str()),
        "WARN" => Ok(Verdict::Warn.as_str()),
        "FAIL" => Ok(Verdict::Fail.as_str()),
        "SKIP" => Ok(Verdict::Skip.as_str()),
        _ => Err("completed review returned unsupported verdict".to_string()),
    }
}

fn completed_review_artifact(
    body: &Value,
    completed_verdict: &str,
    expected_head_sha: &str,
) -> Result<Option<ReviewRunArtifact>, String> {
    let Some(raw) = body.get("review_run_artifact") else {
        return Ok(None);
    };
    let artifact: ReviewRunArtifact = serde_json::from_value(raw.clone()).map_err(|error| {
        format!("completed review returned invalid review_run_artifact: {error}")
    })?;
    artifact.validate().map_err(|error| {
        format!("completed review returned invalid review_run_artifact: {error}")
    })?;
    if artifact.verdict.as_str() != completed_verdict {
        return Err(format!(
            "completed review_run_artifact verdict {} did not match hosted verdict {completed_verdict}",
            artifact.verdict.as_str()
        ));
    }
    if artifact.reviewed_head_sha.as_deref() != Some(expected_head_sha) {
        return Err(format!(
            "completed review_run_artifact reviewed_head_sha {:?} did not match hosted request head_sha {expected_head_sha:?}",
            artifact.reviewed_head_sha
        ));
    }
    Ok(Some(artifact))
}

fn verdict_json_body(body: &Value) -> Value {
    let mut redacted = body.clone();
    redact_review_artifact_keys(&mut redacted);
    redacted
}

fn redact_review_artifact_keys(value: &mut Value) {
    match value {
        Value::Object(fields) => {
            fields.remove("review_run_artifact");
            for value in fields.values_mut() {
                redact_review_artifact_keys(value);
            }
        }
        Value::Array(values) => {
            for value in values {
                redact_review_artifact_keys(value);
            }
        }
        _ => {}
    }
}

fn is_safe_github_output_value(value: &str) -> bool {
    !value.contains(['\n', '\r', '='])
}

fn decision(
    outcome: HostedApiDispatchOutcome,
    exit_code: i32,
    review_id: &str,
    verdict: &str,
    elapsed_seconds: u64,
    poll_attempts: u64,
    consecutive_poll_errors: u64,
    verdict_json: Option<Value>,
    messages: Vec<String>,
) -> HostedApiDispatchDecision {
    let mut github_outputs = BTreeMap::new();
    github_outputs.insert("review-id".to_string(), review_id.to_string());
    github_outputs.insert("verdict".to_string(), verdict.to_string());
    HostedApiDispatchDecision {
        outcome,
        exit_code,
        review_id: review_id.to_string(),
        verdict: verdict.to_string(),
        github_outputs,
        elapsed_seconds,
        poll_attempts,
        consecutive_poll_errors,
        verdict_json,
        review_run_artifact: None,
        review_run_artifact_error: None,
        messages,
    }
}

struct TranscriptHostedApiTransport {
    post: Option<HostedApiHttpResponse>,
    polls: VecDeque<HostedApiHttpResponse>,
}

impl HostedApiDispatchTransport for TranscriptHostedApiTransport {
    fn post_review(
        &mut self,
        _config: &HostedApiDispatchConfig,
    ) -> Result<HostedApiHttpResponse, String> {
        self.post
            .take()
            .ok_or_else(|| "transcript did not include dispatch POST response".to_string())
    }

    fn poll_review(
        &mut self,
        _config: &HostedApiDispatchConfig,
        _review_id: &str,
    ) -> Result<Option<HostedApiHttpResponse>, String> {
        Ok(self.polls.pop_front())
    }

    fn sleep(&mut self, _seconds: u64) {}
}

#[cfg(test)]
mod tests {
    use super::*;
    use cerberus_core::{default_config, review};
    use cerberus_schema::ReviewRequest;
    use serde_json::{json, Value};

    const CLEAN_REQUEST: &str = include_str!("../../../fixtures/review-request/clean.json");

    #[test]
    fn hosted_api_ingress_accepts_valid_review_request_and_redacts_token() {
        let report = hosted_api_ingress_fixture_report(
            &json!({
                "repo": "misty-step/cerberus",
                "pr_number": 459,
                "head_sha": "abc123def456",
                "model": "fake/model",
                "github_token": " request-scope-token ",
                "extra_field": "ignored"
            }),
            7,
        );

        assert_eq!(
            report.schema_version,
            HOSTED_API_INGRESS_FIXTURE_REPORT_VERSION
        );
        assert_eq!(report.http_status, 202);
        assert_eq!(report.body, json!({ "review_id": 7, "status": "queued" }));
        let serialized = serde_json::to_string(&report).expect("report serializes");
        assert!(!serialized.contains("request-scope-token"));
        assert!(!serialized.contains("extra_field"));

        let dispatch = report.dispatch_request.expect("dispatch request");
        assert_eq!(dispatch.repo, "misty-step/cerberus");
        assert_eq!(dispatch.pr_number, 459);
        assert_eq!(dispatch.head_sha, "abc123def456");
        assert_eq!(dispatch.model, "fake/model");
        assert!(dispatch.github_token_present);
    }

    #[test]
    fn hosted_api_ingress_treats_whitespace_token_as_omitted() {
        let report = hosted_api_ingress_fixture_report(
            &json!({
                "repo": "misty-step/cerberus",
                "pr_number": 459,
                "head_sha": "abc123def456",
                "github_token": " \t "
            }),
            8,
        );

        assert_eq!(report.http_status, 202);
        let dispatch = report.dispatch_request.expect("dispatch request");
        assert!(!dispatch.github_token_present);
        assert_eq!(dispatch.model, "");
    }

    #[test]
    fn hosted_api_ingress_rejects_legacy_validation_errors() {
        for (body, expected_error) in [
            (json!({}), "missing required field: repo"),
            (
                json!({ "repo": "", "pr_number": 1, "head_sha": "abc123" }),
                "missing required field: repo",
            ),
            (
                json!({ "repo": "org/repo", "pr_number": "abc", "head_sha": "abc123" }),
                "missing or invalid field: pr_number (must be integer)",
            ),
            (
                json!({ "repo": "org/repo", "pr_number": 1 }),
                "missing required field: head_sha",
            ),
            (
                json!({ "repo": "org/repo", "pr_number": 1, "head_sha": "" }),
                "missing required field: head_sha",
            ),
            (
                json!({
                    "repo": "org/repo",
                    "pr_number": 1,
                    "head_sha": "abc123",
                    "github_token": "good\r\nbad"
                }),
                "invalid field: github_token",
            ),
        ] {
            let report = hosted_api_ingress_fixture_report(&body, 1);
            assert_eq!(report.http_status, 422);
            assert_eq!(report.body, json!({ "error": expected_error }));
            assert!(report.dispatch_request.is_none());
        }
    }

    #[test]
    fn dispatch_accepts_elixir_integer_review_id_response() {
        let decision = run_hosted_api_dispatch_fixture(&transcript(
            settings(false),
            response(202, json!({ "review_id": 459 })),
            vec![response(
                200,
                json!({
                    "status": "completed",
                    "aggregated_verdict": { "verdict": "PASS" }
                }),
            )],
        ))
        .expect("fixture runs");

        assert_eq!(decision.outcome, HostedApiDispatchOutcome::Completed);
        assert_eq!(decision.review_id, "459");
        assert_eq!(decision.github_outputs["review-id"], "459");
        assert_eq!(decision.verdict, "PASS");
    }

    #[test]
    fn completes_after_queued_and_running_polls() {
        let decision = run_hosted_api_dispatch_fixture(&transcript(
            settings(false),
            response(202, json!({ "review_id": "review-459" })),
            vec![
                response(200, json!({ "status": "queued" })),
                response(200, json!({ "status": "running" })),
                response(
                    200,
                    json!({
                        "status": "completed",
                        "aggregated_verdict": { "verdict": "PASS" }
                    }),
                ),
            ],
        ))
        .expect("fixture runs");

        assert_eq!(decision.outcome, HostedApiDispatchOutcome::Completed);
        assert_eq!(decision.exit_code, 0);
        assert_eq!(decision.review_id, "review-459");
        assert_eq!(decision.verdict, "PASS");
        assert_eq!(decision.github_outputs["review-id"], "review-459");
        assert_eq!(decision.github_outputs["verdict"], "PASS");
        assert_eq!(decision.elapsed_seconds, 15);
        assert_eq!(decision.poll_attempts, 3);
    }

    #[test]
    fn fail_on_verdict_controls_failed_completed_review_exit_code() {
        let mut fail_closed = settings(true);
        fail_closed.write_verdict_json = true;
        let decision = run_hosted_api_dispatch_fixture(&transcript(
            fail_closed,
            response(202, json!({ "review_id": "review-459" })),
            vec![response(
                200,
                json!({
                    "status": "completed",
                    "aggregated_verdict": { "verdict": "FAIL" },
                    "summary": "blocked"
                }),
            )],
        ))
        .expect("fixture runs");

        assert_eq!(decision.outcome, HostedApiDispatchOutcome::Completed);
        assert_eq!(decision.exit_code, 1);
        assert_eq!(decision.verdict, "FAIL");
        assert_eq!(decision.elapsed_seconds, 5);
        assert!(decision.verdict_json.is_some());

        let decision = run_hosted_api_dispatch_fixture(&transcript(
            settings(false),
            response(202, json!({ "review_id": "review-459" })),
            vec![response(
                200,
                json!({
                    "status": "completed",
                    "aggregated_verdict": { "verdict": "FAIL" }
                }),
            )],
        ))
        .expect("fixture runs");

        assert_eq!(decision.exit_code, 0);
        assert_eq!(decision.verdict, "FAIL");
    }

    #[test]
    fn verdict_json_redacts_embedded_review_artifact() {
        let artifact = fixture_review_artifact();
        let mut settings = settings(false);
        settings.write_verdict_json = true;
        let decision = run_hosted_api_dispatch_fixture(&transcript(
            settings,
            response(202, json!({ "review_id": "review-459" })),
            vec![response(
                200,
                json!({
                    "status": "completed",
                    "aggregated_verdict": { "verdict": "PASS" },
                    "review_run_artifact": artifact,
                    "diagnostics": {
                        "review_run_artifact": fixture_review_artifact()
                    },
                    "events": [
                        { "review_run_artifact": fixture_review_artifact() }
                    ]
                }),
            )],
        ))
        .expect("fixture runs");

        let verdict_json = decision.verdict_json.expect("verdict json");
        assert_eq!(verdict_json["status"], "completed");
        assert_eq!(verdict_json["aggregated_verdict"]["verdict"], "PASS");
        assert_no_review_artifact_key(&verdict_json);
    }

    #[test]
    fn fail_on_verdict_defaults_to_action_compatibility_true() {
        let raw = json!({
            "api_base_url": "https://cerberus.example",
            "request": {
                "repo": "misty-step/cerberus",
                "pr_number": 459,
                "head_sha": "abc123def456"
            },
            "settings": {
                "timeout_seconds": 600,
                "poll_interval_seconds": 5
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
                        "aggregated_verdict": { "verdict": "FAIL" }
                    }
                }
            ]
        });
        let transcript: HostedApiDispatchTranscript =
            serde_json::from_value(raw).expect("transcript deserializes");

        let decision = run_hosted_api_dispatch_fixture(&transcript).expect("fixture runs");

        assert_eq!(decision.exit_code, 1);
        assert_eq!(decision.verdict, "FAIL");
    }

    #[test]
    fn completed_review_exposes_valid_review_run_artifact() {
        let artifact = fixture_review_artifact();
        let decision = run_hosted_api_dispatch_fixture(&transcript(
            settings(false),
            response(202, json!({ "review_id": "review-459" })),
            vec![response(
                200,
                json!({
                    "status": "completed",
                    "aggregated_verdict": { "verdict": "PASS" },
                    "review_run_artifact": artifact
                }),
            )],
        ))
        .expect("fixture runs");

        let parsed = decision
            .review_run_artifact
            .expect("completed response exposes artifact");
        assert_eq!(parsed.run_id, fixture_review_artifact().run_id);
        assert_eq!(parsed.verdict, Verdict::Pass);
    }

    #[test]
    fn completed_review_rejects_invalid_review_run_artifact() {
        let mut artifact = serde_json::to_value(fixture_review_artifact()).expect("artifact json");
        artifact["stats"]["total"] = json!(999);
        let decision = run_hosted_api_dispatch_fixture(&transcript(
            settings(false),
            response(202, json!({ "review_id": "review-459" })),
            vec![response(
                200,
                json!({
                    "status": "completed",
                    "aggregated_verdict": { "verdict": "PASS" },
                    "review_run_artifact": artifact
                }),
            )],
        ))
        .expect("fixture runs");

        assert_eq!(
            decision.outcome,
            HostedApiDispatchOutcome::InvalidDispatchResponse
        );
        assert_eq!(decision.exit_code, 1);
        assert!(decision
            .messages
            .iter()
            .any(|message| message.contains("review_run_artifact")));
    }

    #[test]
    fn completed_review_rejects_artifact_verdict_mismatch() {
        let artifact = fixture_review_artifact();
        let decision = run_hosted_api_dispatch_fixture(&transcript(
            settings(false),
            response(202, json!({ "review_id": "review-459" })),
            vec![response(
                200,
                json!({
                    "status": "completed",
                    "aggregated_verdict": { "verdict": "FAIL" },
                    "review_run_artifact": artifact
                }),
            )],
        ))
        .expect("fixture runs");

        assert_eq!(
            decision.outcome,
            HostedApiDispatchOutcome::InvalidDispatchResponse
        );
        assert_eq!(decision.verdict, Verdict::Skip.as_str());
        assert!(decision
            .messages
            .iter()
            .any(|message| message.contains("did not match hosted verdict")));
    }

    #[test]
    fn completed_review_rejects_artifact_head_sha_mismatch() {
        let artifact = fixture_review_artifact_for_head("different-head-sha");
        let decision = run_hosted_api_dispatch_fixture(&transcript(
            settings(false),
            response(202, json!({ "review_id": "review-459" })),
            vec![response(
                200,
                json!({
                    "status": "completed",
                    "aggregated_verdict": { "verdict": "PASS" },
                    "review_run_artifact": artifact
                }),
            )],
        ))
        .expect("fixture runs");

        assert_eq!(
            decision.outcome,
            HostedApiDispatchOutcome::InvalidDispatchResponse
        );
        assert_eq!(decision.verdict, Verdict::Skip.as_str());
        assert!(decision
            .messages
            .iter()
            .any(|message| message.contains("reviewed_head_sha")));
    }

    #[test]
    fn rejects_unsafe_dispatch_review_id() {
        let decision = run_hosted_api_dispatch_fixture(&transcript(
            settings(false),
            response(202, json!({ "review_id": "review-459\nverdict=PASS" })),
            vec![response(
                200,
                json!({
                    "status": "completed",
                    "aggregated_verdict": { "verdict": "PASS" }
                }),
            )],
        ))
        .expect("fixture runs");

        assert_eq!(
            decision.outcome,
            HostedApiDispatchOutcome::InvalidDispatchResponse
        );
        assert_eq!(decision.exit_code, 1);
        assert_eq!(decision.github_outputs["review-id"], "");
        assert_eq!(decision.github_outputs["verdict"], "SKIP");
        assert_eq!(decision.poll_attempts, 0);
    }

    #[test]
    fn rejects_completed_review_with_unsupported_verdict() {
        let decision = run_hosted_api_dispatch_fixture(&transcript(
            settings(false),
            response(202, json!({ "review_id": "review-459" })),
            vec![response(
                200,
                json!({
                    "status": "completed",
                    "aggregated_verdict": { "verdict": "FAIL\nverdict=PASS" }
                }),
            )],
        ))
        .expect("fixture runs");

        assert_eq!(
            decision.outcome,
            HostedApiDispatchOutcome::InvalidDispatchResponse
        );
        assert_eq!(decision.exit_code, 1);
        assert_eq!(decision.review_id, "review-459");
        assert_eq!(decision.verdict, "SKIP");
        assert_eq!(decision.github_outputs["review-id"], "review-459");
        assert_eq!(decision.github_outputs["verdict"], "SKIP");
        assert_eq!(decision.poll_attempts, 1);
    }

    #[test]
    fn rejects_non_accepted_dispatch_response() {
        let decision = run_hosted_api_dispatch_fixture(&transcript(
            settings(false),
            response(500, json!({ "error": "unavailable" })),
            vec![response(200, json!({ "status": "completed" }))],
        ))
        .expect("fixture runs");

        assert_eq!(decision.outcome, HostedApiDispatchOutcome::DispatchRejected);
        assert_eq!(decision.exit_code, 1);
        assert_eq!(decision.review_id, "");
        assert_eq!(decision.verdict, "SKIP");
        assert_eq!(decision.poll_attempts, 0);
    }

    #[test]
    fn fails_closed_when_dispatch_body_has_no_review_id() {
        let decision = run_hosted_api_dispatch_fixture(&transcript(
            settings(false),
            response(202, json!({ "ok": true })),
            vec![response(200, json!({ "status": "completed" }))],
        ))
        .expect("fixture runs");

        assert_eq!(
            decision.outcome,
            HostedApiDispatchOutcome::InvalidDispatchResponse
        );
        assert_eq!(decision.exit_code, 1);
        assert_eq!(decision.github_outputs["review-id"], "");
        assert_eq!(decision.github_outputs["verdict"], "SKIP");
        assert_eq!(decision.poll_attempts, 0);
    }

    #[test]
    fn exhausts_consecutive_poll_errors() {
        let mut settings = settings(false);
        settings.max_poll_errors = 2;
        let decision = run_hosted_api_dispatch_fixture(&transcript(
            settings,
            response(202, json!({ "review_id": "review-459" })),
            vec![
                response(503, json!({ "error": "first" })),
                response(502, json!({ "error": "second" })),
                response(
                    200,
                    json!({
                        "status": "completed",
                        "aggregated_verdict": { "verdict": "PASS" }
                    }),
                ),
            ],
        ))
        .expect("fixture runs");

        assert_eq!(
            decision.outcome,
            HostedApiDispatchOutcome::PollErrorsExhausted
        );
        assert_eq!(decision.exit_code, 1);
        assert_eq!(decision.consecutive_poll_errors, 2);
        assert_eq!(decision.poll_attempts, 2);
        assert_eq!(decision.elapsed_seconds, 10);
        assert_eq!(decision.verdict, "SKIP");
    }

    #[test]
    fn times_out_when_transcript_consumes_timeout_budget() {
        let mut settings = settings(false);
        settings.timeout_seconds = 10;
        let decision = run_hosted_api_dispatch_fixture(&transcript(
            settings,
            response(202, json!({ "review_id": "review-459" })),
            vec![
                response(200, json!({ "status": "queued" })),
                response(200, json!({ "status": "running" })),
            ],
        ))
        .expect("fixture runs");

        assert_eq!(decision.outcome, HostedApiDispatchOutcome::TimedOut);
        assert_eq!(decision.exit_code, 1);
        assert_eq!(decision.elapsed_seconds, 10);
        assert_eq!(decision.verdict, "SKIP");
    }

    #[test]
    fn failed_review_status_exits_with_skip_verdict() {
        let decision = run_hosted_api_dispatch_fixture(&transcript(
            settings(false),
            response(202, json!({ "review_id": "review-459" })),
            vec![response(200, json!({ "status": "failed" }))],
        ))
        .expect("fixture runs");

        assert_eq!(decision.outcome, HostedApiDispatchOutcome::ReviewFailed);
        assert_eq!(decision.exit_code, 1);
        assert_eq!(decision.review_id, "review-459");
        assert_eq!(decision.verdict, "SKIP");
        assert_eq!(decision.elapsed_seconds, 5);
    }

    fn transcript(
        settings: HostedApiDispatchSettings,
        post: HostedApiHttpResponse,
        polls: Vec<HostedApiHttpResponse>,
    ) -> HostedApiDispatchTranscript {
        HostedApiDispatchTranscript {
            api_base_url: "https://cerberus.example".to_string(),
            request: HostedApiDispatchRequest {
                repo: "misty-step/cerberus".to_string(),
                pr_number: 459,
                head_sha: "abc123def456".to_string(),
                model: "fake/model".to_string(),
                github_token_present: true,
            },
            settings,
            post,
            polls,
        }
    }

    fn settings(fail_on_verdict: bool) -> HostedApiDispatchSettings {
        HostedApiDispatchSettings {
            timeout_seconds: 600,
            poll_interval_seconds: 5,
            max_poll_errors: 10,
            fail_on_verdict,
            write_verdict_json: false,
        }
    }

    fn response(http_status: u16, body: Value) -> HostedApiHttpResponse {
        HostedApiHttpResponse { http_status, body }
    }

    fn fixture_review_artifact() -> cerberus_schema::ReviewRunArtifact {
        fixture_review_artifact_for_head("abc123def456")
    }

    fn fixture_review_artifact_for_head(head_sha: &str) -> cerberus_schema::ReviewRunArtifact {
        let mut request: ReviewRequest =
            serde_json::from_str(CLEAN_REQUEST).expect("request fixture parses");
        request.change.head_sha = Some(head_sha.to_string());
        review(&request, &default_config()).expect("core review succeeds")
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
}
