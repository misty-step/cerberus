use anyhow::Result;
use serde::{Deserialize, Serialize};

use crate::digest::{request_digest, sha256_digest};
use crate::receipt::{ReceiptValidationStatus, ReviewReceiptBundle};
use crate::schema::{ContextCapabilities, LifecycleState, ReviewArtifact, ReviewRequest};

pub const CRUCIBLE_PRODUCER_MANIFEST_SCHEMA: &str = "cerberus.crucible_producer_manifest.v1";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CrucibleProducerManifest {
    pub schema_version: String,
    pub consumer: String,
    pub request: ProducerRequestRef,
    pub artifact: ProducerArtifactRef,
    pub receipt_bundle: ProducerReceiptBundleRef,
    pub grader_input: ProducerGraderInput,
    pub validation: ProducerValidation,
    pub boundary: ProducerBoundary,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProducerRequestRef {
    pub request_id: String,
    pub request_digest: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ProducerArtifactRef {
    pub artifact_id: String,
    pub artifact_uri: String,
    pub artifact_digest: String,
    pub schema_version: String,
    pub finding_count: usize,
    pub comment_count: usize,
    pub capability_tier: String,
    pub context_capabilities: ContextCapabilities,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProducerReceiptBundleRef {
    pub schema_version: String,
    pub receipt_bundle_uri: String,
    pub receipt_bundle_digest: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub transcript_uri: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub execution_plan_uri: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProducerGraderInput {
    pub format: String,
    pub artifact_uri: String,
    pub findings_path: String,
    pub finding_id_path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProducerValidation {
    pub status: ReceiptValidationStatus,
    pub trusted_for_grading: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProducerBoundary {
    pub scorer_owner: String,
    pub includes_score: bool,
    pub note: String,
}

pub struct CrucibleProducerManifestInput<'a> {
    pub request: &'a ReviewRequest,
    pub artifact: &'a ReviewArtifact,
    pub receipt_bundle: &'a ReviewReceiptBundle,
    pub receipt_bundle_uri: String,
}

pub fn build_crucible_producer_manifest(
    input: CrucibleProducerManifestInput<'_>,
) -> Result<CrucibleProducerManifest> {
    let request_digest = request_digest(input.request)?;
    let receipt_bundle_digest = stable_json_digest(input.receipt_bundle)?;
    let trusted_for_grading = input.receipt_bundle.validation.status
        == ReceiptValidationStatus::Passed
        && matches!(
            input.artifact.lifecycle_state,
            LifecycleState::Completed | LifecycleState::CompletedDegraded
        );
    Ok(CrucibleProducerManifest {
        schema_version: CRUCIBLE_PRODUCER_MANIFEST_SCHEMA.to_string(),
        consumer: "crucible".to_string(),
        request: ProducerRequestRef {
            request_id: input.request.request_id.clone(),
            request_digest,
        },
        artifact: ProducerArtifactRef {
            artifact_id: input.artifact.artifact_id.clone(),
            artifact_uri: input.receipt_bundle.artifact_uri.clone(),
            artifact_digest: input.receipt_bundle.artifact_digest.clone(),
            schema_version: input.artifact.schema_version.clone(),
            finding_count: input.artifact.findings.len(),
            comment_count: input.artifact.comments.len(),
            capability_tier: input.receipt_bundle.capability_tier.clone(),
            context_capabilities: input.receipt_bundle.context_capabilities.clone(),
        },
        receipt_bundle: ProducerReceiptBundleRef {
            schema_version: input.receipt_bundle.schema_version.clone(),
            receipt_bundle_uri: input.receipt_bundle_uri,
            receipt_bundle_digest,
            transcript_uri: input.receipt_bundle.transcript_uri.clone(),
            execution_plan_uri: input.receipt_bundle.execution_plan_uri.clone(),
        },
        grader_input: ProducerGraderInput {
            format: "cerberus.review_artifact.v1".to_string(),
            artifact_uri: input.receipt_bundle.artifact_uri.clone(),
            findings_path: "findings".to_string(),
            finding_id_path: "findings[].id".to_string(),
        },
        validation: ProducerValidation {
            status: input.receipt_bundle.validation.status.clone(),
            trusted_for_grading,
        },
        boundary: ProducerBoundary {
            scorer_owner: "crucible".to_string(),
            includes_score: false,
            note: "Cerberus produced the validated review artifact and redacted receipts only; Crucible owns grading, intervals, adjudication, and export.".to_string(),
        },
    })
}

fn stable_json_digest(value: &impl Serialize) -> Result<String> {
    let mut serialized = serde_json::to_string_pretty(value)?;
    serialized.push('\n');
    Ok(sha256_digest(serialized.as_bytes()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::receipt::{build_review_receipt_bundle, ReceiptBundleInput};
    use crate::schema::{ReviewTelemetry, REVIEW_ARTIFACT_SCHEMA};

    #[test]
    fn manifest_points_crucible_at_the_artifact_findings_array() {
        let request = request();
        let artifact = artifact();
        let telemetry = ReviewTelemetry::default();
        let bundle = build_review_receipt_bundle(ReceiptBundleInput {
            request: &request,
            artifact: &artifact,
            harness: "fixture",
            telemetry: &telemetry,
            transcript: "elapsed_ms: 9",
            artifact_uri: "target/cerberus/crucible-producer/artifact.json".to_string(),
            transcript_uri: Some("target/cerberus/crucible-producer/transcript.txt".to_string()),
            execution_plan_uri: Some(
                "target/cerberus/crucible-producer/execution_plan.json".to_string(),
            ),
            validation_failed: false,
        })
        .unwrap();

        let manifest = build_crucible_producer_manifest(CrucibleProducerManifestInput {
            request: &request,
            artifact: &artifact,
            receipt_bundle: &bundle,
            receipt_bundle_uri: "target/cerberus/crucible-producer/receipt-bundle.json".to_string(),
        })
        .unwrap();

        assert_eq!(manifest.schema_version, CRUCIBLE_PRODUCER_MANIFEST_SCHEMA);
        assert_eq!(manifest.consumer, "crucible");
        assert_eq!(manifest.artifact.schema_version, REVIEW_ARTIFACT_SCHEMA);
        assert_eq!(manifest.artifact.finding_count, 1);
        assert_eq!(manifest.grader_input.format, REVIEW_ARTIFACT_SCHEMA);
        assert_eq!(manifest.grader_input.findings_path, "findings");
        assert_eq!(manifest.grader_input.finding_id_path, "findings[].id");
        assert!(manifest.validation.trusted_for_grading);
        assert_eq!(manifest.boundary.scorer_owner, "crucible");
        assert!(!manifest.boundary.includes_score);
    }

    #[test]
    fn manifest_does_not_mark_failed_validation_as_gradeable() {
        let request = request();
        let artifact = artifact();
        let telemetry = ReviewTelemetry::default();
        let bundle = build_review_receipt_bundle(ReceiptBundleInput {
            request: &request,
            artifact: &artifact,
            harness: "fixture",
            telemetry: &telemetry,
            transcript: "elapsed_ms: 9",
            artifact_uri: "target/cerberus/crucible-producer/artifact.json".to_string(),
            transcript_uri: None,
            execution_plan_uri: None,
            validation_failed: true,
        })
        .unwrap();

        let manifest = build_crucible_producer_manifest(CrucibleProducerManifestInput {
            request: &request,
            artifact: &artifact,
            receipt_bundle: &bundle,
            receipt_bundle_uri: "target/cerberus/crucible-producer/receipt-bundle.json".to_string(),
        })
        .unwrap();

        assert_eq!(manifest.validation.status, ReceiptValidationStatus::Failed);
        assert!(!manifest.validation.trusted_for_grading);
    }

    fn request() -> ReviewRequest {
        serde_json::from_str(include_str!("../fixtures/requests/diff-only.json")).unwrap()
    }

    fn artifact() -> ReviewArtifact {
        let raw = include_str!("../fixtures/harness/valid-review.txt").replace(
            "{{context_capabilities}}",
            r#"{"diff":true,"repo_head":false,"repo_base":false,"local_runtime":false,"remote_runtime":false,"external_research":"forbid"}"#,
        );
        serde_json::from_str(&raw).unwrap()
    }
}
