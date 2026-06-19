use crate::AdapterError;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;

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
    pub messages: Vec<String>,
}

pub fn run_hosted_api_dispatch_fixture(
    transcript: &HostedApiDispatchTranscript,
) -> Result<HostedApiDispatchDecision, AdapterError> {
    validate_transcript(transcript)?;

    let mut messages = Vec::new();
    if transcript.post.http_status != 202 {
        messages.push(format!(
            "dispatch POST returned HTTP {}, expected 202",
            transcript.post.http_status
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

    let Some(review_id) = string_field(&transcript.post.body, "review_id") else {
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

    let mut elapsed_seconds = 0;
    let mut poll_attempts = 0;
    let mut consecutive_poll_errors = 0;

    for poll in &transcript.polls {
        if elapsed_seconds >= transcript.settings.timeout_seconds {
            messages.push(format!(
                "timed out after {elapsed_seconds}s while waiting for review {review_id}"
            ));
            return Ok(decision(
                HostedApiDispatchOutcome::TimedOut,
                1,
                review_id,
                "SKIP",
                elapsed_seconds,
                poll_attempts,
                consecutive_poll_errors,
                None,
                messages,
            ));
        }

        elapsed_seconds += transcript.settings.poll_interval_seconds;
        poll_attempts += 1;
        if poll.http_status != 200 {
            consecutive_poll_errors += 1;
            messages.push(format!(
                "poll attempt {poll_attempts} returned HTTP {}",
                poll.http_status
            ));
            if consecutive_poll_errors >= transcript.settings.max_poll_errors {
                messages.push(format!(
                    "polling stopped after {consecutive_poll_errors} consecutive HTTP errors"
                ));
                return Ok(decision(
                    HostedApiDispatchOutcome::PollErrorsExhausted,
                    1,
                    review_id,
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
                    review_id,
                    "SKIP",
                    elapsed_seconds,
                    poll_attempts,
                    consecutive_poll_errors,
                    None,
                    messages,
                ));
            }
            Some("completed") => {
                let verdict = completed_verdict(&poll.body);
                let exit_code = i32::from(transcript.settings.fail_on_verdict && verdict == "FAIL");
                if exit_code != 0 {
                    messages.push("fail-on-verdict converted FAIL verdict to exit 1".to_string());
                }
                let verdict_json = transcript
                    .settings
                    .write_verdict_json
                    .then(|| poll.body.clone());
                return Ok(decision(
                    HostedApiDispatchOutcome::Completed,
                    exit_code,
                    review_id,
                    &verdict,
                    elapsed_seconds,
                    poll_attempts,
                    consecutive_poll_errors,
                    verdict_json,
                    messages,
                ));
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

    if elapsed_seconds >= transcript.settings.timeout_seconds {
        messages.push(format!(
            "timed out after {elapsed_seconds}s while waiting for review {review_id}"
        ));
        return Ok(decision(
            HostedApiDispatchOutcome::TimedOut,
            1,
            review_id,
            "SKIP",
            elapsed_seconds,
            poll_attempts,
            consecutive_poll_errors,
            None,
            messages,
        ));
    }

    messages.push(format!(
        "transcript ended before review {review_id} reached a terminal status"
    ));
    Ok(decision(
        HostedApiDispatchOutcome::TranscriptExhausted,
        1,
        review_id,
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

fn validate_transcript(transcript: &HostedApiDispatchTranscript) -> Result<(), AdapterError> {
    non_empty("api_base_url", &transcript.api_base_url)?;
    non_empty("request.repo", &transcript.request.repo)?;
    if transcript.request.pr_number == 0 {
        return invalid("request.pr_number must be greater than zero");
    }
    non_empty("request.head_sha", &transcript.request.head_sha)?;
    if transcript.settings.poll_interval_seconds == 0 {
        return invalid("settings.poll_interval_seconds must be greater than zero");
    }
    if transcript.settings.max_poll_errors == 0 {
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

fn string_field<'a>(body: &'a Value, field: &str) -> Option<&'a str> {
    body.get(field)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
}

fn completed_verdict(body: &Value) -> String {
    body.get("aggregated_verdict")
        .and_then(|value| value.get("verdict"))
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or("SKIP")
        .to_string()
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
        messages,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

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
}
