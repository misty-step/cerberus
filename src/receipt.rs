use anyhow::Result;
use serde::{Deserialize, Serialize};

use crate::digest::{request_digest, sha256_digest};
use crate::prompt::REVIEW_DOCTRINE;
use crate::schema::{
    ContextCapabilities, LifecycleState, ReviewArtifact, ReviewRequest, ReviewTelemetry, Usage,
};

pub const REVIEW_RECEIPT_BUNDLE_SCHEMA: &str = "cerberus.review_receipt_bundle.v1";
const ARTIFACT_VALIDATION_FAILED: &str = "artifact_validation_failed";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ReviewReceiptBundle {
    pub schema_version: String,
    pub request_id: String,
    pub request_digest: String,
    pub artifact_id: String,
    pub artifact_digest: String,
    pub harness: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub model: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub usage: Option<Usage>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cost_usd: Option<f64>,
    pub latency_ms: u64,
    pub capability_tier: String,
    /// sha256 of the review doctrine text (src/review_doctrine.md) embedded
    /// in the prompt for this run — including the mandatory model-boundary
    /// dimension (backlog 023). Recorded so any receipt can show which
    /// doctrine version, and therefore which mandatory review dimensions,
    /// were in force, without depending on the model to self-report it.
    pub review_doctrine_digest: String,
    pub context_capabilities: ContextCapabilities,
    pub artifact_uri: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub transcript_uri: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub execution_plan_uri: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reviewer_plan_uri: Option<String>,
    pub validation: ReceiptValidation,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReceiptValidation {
    pub status: ReceiptValidationStatus,
    pub trusted_for_posting: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ReceiptValidationStatus {
    Passed,
    Failed,
}

pub struct ReceiptBundleInput<'a> {
    pub request: &'a ReviewRequest,
    pub artifact: &'a ReviewArtifact,
    pub harness: &'a str,
    pub telemetry: &'a ReviewTelemetry,
    pub transcript: &'a str,
    pub artifact_uri: String,
    pub transcript_uri: Option<String>,
    pub execution_plan_uri: Option<String>,
    pub reviewer_plan_uri: Option<String>,
    pub validation_failed: bool,
}

pub fn build_review_receipt_bundle(input: ReceiptBundleInput<'_>) -> Result<ReviewReceiptBundle> {
    let request_digest = request_digest(input.request)?;
    let artifact_digest = artifact_digest(input.artifact)?;
    let validation = receipt_validation(input.artifact, input.validation_failed);
    let context_capabilities = ContextCapabilities::from_request(input.request);
    let usage = input
        .telemetry
        .usage
        .clone()
        .or_else(|| artifact_usage(input.artifact));
    let cost_usd = input
        .telemetry
        .cost_usd
        .or_else(|| usage.as_ref().and_then(|usage| usage.cost_usd))
        .or_else(|| artifact_cost_usd(input.artifact));
    Ok(ReviewReceiptBundle {
        schema_version: REVIEW_RECEIPT_BUNDLE_SCHEMA.to_string(),
        request_id: input.request.request_id.clone(),
        request_digest,
        artifact_id: input.artifact.artifact_id.clone(),
        artifact_digest,
        harness: input.harness.to_string(),
        model: input
            .telemetry
            .model
            .clone()
            .or_else(|| artifact_model(input.artifact)),
        usage,
        cost_usd,
        latency_ms: transcript_elapsed_ms(input.transcript)
            .unwrap_or(input.artifact.run.duration_ms),
        capability_tier: capability_tier(&context_capabilities).to_string(),
        review_doctrine_digest: sha256_digest(REVIEW_DOCTRINE.as_bytes()),
        context_capabilities,
        artifact_uri: input.artifact_uri,
        transcript_uri: input.transcript_uri,
        execution_plan_uri: input.execution_plan_uri,
        reviewer_plan_uri: input.reviewer_plan_uri,
        validation,
    })
}

fn artifact_digest(artifact: &ReviewArtifact) -> Result<String> {
    let mut serialized = serde_json::to_string_pretty(artifact)?;
    serialized.push('\n');
    Ok(sha256_digest(serialized.as_bytes()))
}

fn receipt_validation(artifact: &ReviewArtifact, validation_failed: bool) -> ReceiptValidation {
    let trusted_for_posting = !validation_failed
        && matches!(
            artifact.lifecycle_state,
            LifecycleState::Completed | LifecycleState::CompletedDegraded
        );
    ReceiptValidation {
        status: if validation_failed {
            ReceiptValidationStatus::Failed
        } else {
            ReceiptValidationStatus::Passed
        },
        trusted_for_posting,
        error: validation_failed.then(|| ARTIFACT_VALIDATION_FAILED.to_string()),
    }
}

pub(crate) fn capability_tier(capabilities: &ContextCapabilities) -> &'static str {
    if capabilities.remote_runtime {
        "remote_runtime"
    } else if capabilities.local_runtime {
        "local_runtime"
    } else if capabilities.repo_head && capabilities.repo_base {
        "repo_base_and_head"
    } else if capabilities.repo_head {
        "repo_head"
    } else if capabilities.diff {
        "diff_only"
    } else {
        "metadata_only"
    }
}

fn artifact_model(artifact: &ReviewArtifact) -> Option<String> {
    artifact
        .receipts
        .iter()
        .find_map(|receipt| receipt.model.clone())
}

fn artifact_usage(artifact: &ReviewArtifact) -> Option<Usage> {
    artifact
        .receipts
        .iter()
        .find_map(|receipt| receipt.usage.clone())
}

fn artifact_cost_usd(artifact: &ReviewArtifact) -> Option<f64> {
    artifact.run.cost_usd.or_else(|| {
        artifact
            .receipts
            .iter()
            .find_map(|receipt| receipt.usage.as_ref().and_then(|usage| usage.cost_usd))
    })
}

fn transcript_elapsed_ms(transcript: &str) -> Option<u64> {
    transcript.lines().find_map(|line| {
        line.strip_prefix("elapsed_ms: ")
            .and_then(|value| value.parse::<u64>().ok())
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::harness::ExecutionPlan;
    use crate::kernel::ReviewRun;
    use crate::schema::{
        Coverage, LifecycleState, Receipt, ReceiptRole, ReceiptStatus, ReviewArtifact,
        ReviewRequest, Summary, Verdict,
    };

    #[test]
    fn receipt_bundle_is_deterministic_for_same_request_and_artifact() {
        let request = request();
        let run = run_for(&request);

        let first = build_review_receipt_bundle(input(&request, &run, false)).unwrap();
        let second = build_review_receipt_bundle(input(&request, &run, false)).unwrap();

        assert_eq!(first, second);
        assert_eq!(first.schema_version, REVIEW_RECEIPT_BUNDLE_SCHEMA);
        assert_eq!(first.request_digest, request_digest(&request).unwrap());
        assert!(first.artifact_digest.starts_with("sha256:"));
        assert_eq!(first.capability_tier, "diff_only");
        assert_eq!(first.validation.status, ReceiptValidationStatus::Passed);
        assert!(first.validation.trusted_for_posting);
    }

    // Backlog 023: the receipt bundle is the durable surface that shows which
    // review doctrine -- and therefore which mandatory dimensions, e.g. the
    // model-boundary one -- governed a given run, without depending on the
    // model to self-report it.
    #[test]
    fn receipt_bundle_records_the_review_doctrine_digest() {
        let request = request();
        let run = run_for(&request);

        let bundle = build_review_receipt_bundle(input(&request, &run, false)).unwrap();

        assert_eq!(
            bundle.review_doctrine_digest,
            sha256_digest(crate::prompt::REVIEW_DOCTRINE.as_bytes())
        );
    }

    // Backlog 011: `!serialized.contains("secret")`-style checks are
    // tautological here -- ReviewReceiptBundle structurally has no field
    // that could ever hold a raw prompt path, secret name, or transcript
    // excerpt (only `*_uri` pointers), so those assertions would pass even
    // if a real leak existed elsewhere. The positive contract that actually
    // constrains future changes: the bundle's serialized field set is
    // exactly this allowlist. Adding any new field forces a conscious,
    // visible update here -- the real backstop against a future field
    // accidentally carrying raw content.
    fn assert_receipt_bundle_field_allowlist(bundle: &ReviewReceiptBundle) {
        let value = serde_json::to_value(bundle).unwrap();
        let fields: std::collections::BTreeSet<&str> = value
            .as_object()
            .unwrap()
            .keys()
            .map(|key| key.as_str())
            .collect();
        let allowed: std::collections::BTreeSet<&str> = [
            "schema_version",
            "request_id",
            "request_digest",
            "artifact_id",
            "artifact_digest",
            "harness",
            "model",
            "usage",
            "cost_usd",
            "latency_ms",
            "capability_tier",
            "review_doctrine_digest",
            "context_capabilities",
            "artifact_uri",
            "transcript_uri",
            "execution_plan_uri",
            "reviewer_plan_uri",
            "validation",
        ]
        .into_iter()
        .collect();
        assert_eq!(
            fields, allowed,
            "receipt bundle field set changed -- if this is a deliberate new field, \
             confirm it holds a URI/digest/pointer, never raw prompt or transcript \
             content, before updating this allowlist"
        );
    }

    #[test]
    fn receipt_bundle_exposes_only_the_allowlisted_fields_even_with_sensitive_input() {
        let request = request();
        let mut run = run_for(&request);
        run.execution_plan.command = "/tmp/cerberus-private/master-prompt.md".to_string();
        run.execution_plan.args = vec![
            "--file".to_string(),
            "/tmp/cerberus-private/review-request.json".to_string(),
        ];
        run.transcript = "elapsed_ms: 9\nGH_TOKEN=should-not-leak\nsecret-value".to_string();

        let bundle = build_review_receipt_bundle(input(&request, &run, false)).unwrap();

        assert_receipt_bundle_field_allowlist(&bundle);
        assert_eq!(bundle.latency_ms, 9);
    }

    #[test]
    fn receipt_bundle_records_validation_failure_without_trusting_posting() {
        let request = request();
        let run = run_for(&request);

        let bundle = build_review_receipt_bundle(input(&request, &run, true)).unwrap();

        assert_eq!(bundle.validation.status, ReceiptValidationStatus::Failed);
        assert!(!bundle.validation.trusted_for_posting);
        assert_eq!(
            bundle.validation.error.as_deref(),
            Some(ARTIFACT_VALIDATION_FAILED)
        );
    }

    #[test]
    fn receipt_bundle_uses_request_capabilities_when_artifact_overstates_context() {
        let request = request();
        let mut run = run_for(&request);
        run.artifact.context_capabilities.repo_base = true;
        run.artifact.context_capabilities.local_runtime = true;

        let bundle = build_review_receipt_bundle(input(&request, &run, true)).unwrap();

        assert_eq!(bundle.capability_tier, "diff_only");
        assert!(!bundle.context_capabilities.repo_base);
        assert!(!bundle.context_capabilities.local_runtime);
        assert_eq!(bundle.validation.status, ReceiptValidationStatus::Failed);
    }

    #[test]
    fn receipt_bundle_sanitizes_validation_failure_details() {
        let request = request();
        let mut run = run_for(&request);
        run.artifact.schema_version =
            "cerberus.review_artifact.v1 GH_TOKEN master-prompt.md review-request.json".to_string();
        run.transcript = "elapsed_ms: 9\nGH_TOKEN=secret\nraw transcript excerpt".to_string();

        let bundle = build_review_receipt_bundle(input(&request, &run, true)).unwrap();

        // Positive contract: the validation error is the generic constant,
        // never the raw (attacker-influenced) schema_version string it was
        // derived from.
        assert_eq!(
            bundle.validation.error.as_deref(),
            Some(ARTIFACT_VALIDATION_FAILED)
        );
        assert_receipt_bundle_field_allowlist(&bundle);
    }

    fn input<'a>(
        request: &'a ReviewRequest,
        run: &'a ReviewRun,
        validation_failed: bool,
    ) -> ReceiptBundleInput<'a> {
        ReceiptBundleInput {
            request,
            artifact: &run.artifact,
            harness: &run.execution_plan.harness,
            telemetry: &run.telemetry,
            transcript: &run.transcript,
            artifact_uri: "target/cerberus/artifact.json".to_string(),
            transcript_uri: Some("target/cerberus/transcript.txt".to_string()),
            execution_plan_uri: Some("target/cerberus/execution_plan.json".to_string()),
            reviewer_plan_uri: Some("target/cerberus/reviewer_plan.json".to_string()),
            validation_failed,
        }
    }

    fn request() -> ReviewRequest {
        crate::test_support::minimal_review_request()
    }

    fn run_for(request: &ReviewRequest) -> ReviewRun {
        let artifact = ReviewArtifact {
            schema_version: crate::schema::REVIEW_ARTIFACT_SCHEMA.to_string(),
            artifact_id: "artifact-1".to_string(),
            request_id: request.request_id.clone(),
            request_digest: request_digest(request).unwrap(),
            lifecycle_state: LifecycleState::Completed,
            verdict: Verdict::Pass,
            context_capabilities: ContextCapabilities::from_request(request),
            summary: Summary {
                title: "ok".to_string(),
                body: "ok".to_string(),
                analysis: String::new(),
                residual_risk: Vec::new(),
            },
            findings: Vec::new(),
            comments: Vec::new(),
            suggested_fixes: Vec::new(),
            citations: Vec::new(),
            receipts: vec![Receipt {
                id: "receipt-master".to_string(),
                role: ReceiptRole::Master,
                perspective: None,
                model: Some("fixture-model".to_string()),
                provider: None,
                harness: Some("fixture".to_string()),
                status: ReceiptStatus::Completed,
                verdict: Some(Verdict::Pass),
                summary: Some("ok".to_string()),
                artifact_digest: None,
                transcript_uri: None,
                usage: Some(Usage {
                    prompt_tokens: Some(10),
                    completion_tokens: Some(5),
                    cost_usd: Some(0.01),
                }),
                error: None,
            }],
            run: crate::schema::RunInfo {
                engine_version: "cerberus-fixture".to_string(),
                config_digest: "sha256:fixture".to_string(),
                started_at: "0".to_string(),
                finished_at: "1".to_string(),
                duration_ms: 1,
                cost_usd: None,
                coverage: Coverage {
                    files_reviewed: Vec::new(),
                    files_with_findings: Vec::new(),
                },
            },
            errors: Vec::new(),
        };
        ReviewRun {
            artifact,
            transcript: "elapsed_ms: 17".to_string(),
            execution_plan: ExecutionPlan {
                harness: "fixture".to_string(),
                command: "fixtures/harness/valid-review.txt".to_string(),
                args: Vec::new(),
                cwd: ".".to_string(),
                timeout_ms: 1000,
                env_allowlist: Vec::new(),
                context_capabilities: ContextCapabilities::from_request(request),
                prompt_transport: "fixture template".to_string(),
                private_material_in_argv: false,
                workspace_mode: "diff_packet".to_string(),
                runtime_transcripts: Vec::new(),
            },
            reviewer_plan: crate::orchestration::build_reviewer_plan(
                request,
                &ExecutionPlan {
                    harness: "fixture".to_string(),
                    command: "fixtures/harness/valid-review.txt".to_string(),
                    args: Vec::new(),
                    cwd: ".".to_string(),
                    timeout_ms: 1000,
                    env_allowlist: Vec::new(),
                    context_capabilities: ContextCapabilities::from_request(request),
                    prompt_transport: "fixture template".to_string(),
                    private_material_in_argv: false,
                    workspace_mode: "diff_packet".to_string(),
                    runtime_transcripts: Vec::new(),
                },
                &Default::default(),
            )
            .unwrap(),
            telemetry: Default::default(),
        }
    }
}
