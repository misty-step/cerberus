use anyhow::Result;
use serde::{Deserialize, Serialize};

use crate::digest::request_digest;
use crate::harness::ExecutionPlan;
use crate::receipt::capability_tier;
use crate::schema::{ChangedFile, ContextCapabilities, FileStatus, ReviewRequest, ReviewTelemetry};

pub const REVIEWER_PLAN_SCHEMA: &str = "cerberus.reviewer_plan.v1";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ReviewerPlanReceipt {
    pub schema_version: String,
    pub request_id: String,
    pub request_digest: String,
    pub diff_understanding: DiffUnderstanding,
    pub lane_decision: LaneDecision,
    pub master_lane: ReviewerLanePlan,
    pub child_lanes: Vec<ReviewerLanePlan>,
    pub synthesis: SynthesisPlan,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct DiffUnderstanding {
    pub changed_surfaces: Vec<ChangedSurface>,
    pub summary: String,
    pub risk_shape: Vec<String>,
    pub available_context: ContextCapabilities,
    pub skipped_context: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ChangedSurface {
    pub path: String,
    pub status: FileStatus,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub additions: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub deletions: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub old_path: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct LaneDecision {
    pub mode: LaneDecisionMode,
    pub reason: String,
    pub stop_condition: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cost_budget_usd: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum LaneDecisionMode {
    SingleMaster,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReviewerLanePlan {
    pub id: String,
    pub role: String,
    pub objective: String,
    pub scope: Vec<String>,
    pub allowed_context_tier: String,
    pub substrate: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub model: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cost_budget_usd: Option<String>,
    pub stop_condition: String,
    pub expected_output: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SynthesisPlan {
    pub strategy: String,
    pub artifact_contract: String,
    pub validation_gate: String,
    pub notes: Vec<String>,
}

pub fn build_reviewer_plan(
    request: &ReviewRequest,
    execution_plan: &ExecutionPlan,
    telemetry: &ReviewTelemetry,
) -> Result<ReviewerPlanReceipt> {
    let available_context = ContextCapabilities::from_request(request);
    let changed_surfaces = changed_surfaces(&request.change.files);
    let context_tier = capability_tier(&available_context).to_string();
    let scope = if changed_surfaces.is_empty() {
        vec!["diff packet".to_string()]
    } else {
        changed_surfaces
            .iter()
            .map(|surface| surface.path.clone())
            .collect()
    };

    Ok(ReviewerPlanReceipt {
        schema_version: REVIEWER_PLAN_SCHEMA.to_string(),
        request_id: request.request_id.clone(),
        request_digest: request_digest(request)?,
        diff_understanding: DiffUnderstanding {
            summary: diff_summary(&changed_surfaces),
            risk_shape: risk_shape(&changed_surfaces, &available_context),
            changed_surfaces,
            skipped_context: skipped_context(&available_context),
            available_context,
        },
        lane_decision: LaneDecision {
            mode: LaneDecisionMode::SingleMaster,
            reason: "The current orchestrator slice records the existing single-master path; child lane launch is disabled until the reviewer-lane substrate lands.".to_string(),
            stop_condition: "Emit exactly one ReviewArtifact.v1 candidate and pass validate_artifact_for_request, or fail closed.".to_string(),
            cost_budget_usd: None,
        },
        master_lane: ReviewerLanePlan {
            id: "lane-master".to_string(),
            role: "master".to_string(),
            objective: "Review the change using the declared context and synthesize the final artifact.".to_string(),
            scope,
            allowed_context_tier: context_tier,
            substrate: execution_plan.harness.clone(),
            model: telemetry.model.clone(),
            cost_budget_usd: None,
            stop_condition: "Stop after a validated ReviewArtifact.v1 is emitted or the substrate fails.".to_string(),
            expected_output: "ReviewArtifact.v1".to_string(),
        },
        child_lanes: Vec::new(),
        synthesis: SynthesisPlan {
            strategy: "single_master_synthesis".to_string(),
            artifact_contract: "ReviewArtifact.v1".to_string(),
            validation_gate: "validate_artifact_for_request".to_string(),
            notes: vec![
                "No child lanes were launched in this run.".to_string(),
                "Future child-lane evidence must be synthesized into the same artifact and cannot bypass validation.".to_string(),
            ],
        },
    })
}

fn changed_surfaces(files: &[ChangedFile]) -> Vec<ChangedSurface> {
    files
        .iter()
        .map(|file| ChangedSurface {
            path: file.path.clone(),
            status: file.status.clone(),
            additions: file.additions,
            deletions: file.deletions,
            old_path: file.old_path.clone(),
        })
        .collect()
}

fn diff_summary(changed_surfaces: &[ChangedSurface]) -> String {
    let files = changed_surfaces.len();
    let additions: u32 = changed_surfaces
        .iter()
        .filter_map(|surface| surface.additions)
        .sum();
    let deletions: u32 = changed_surfaces
        .iter()
        .filter_map(|surface| surface.deletions)
        .sum();
    format!("{files} changed file(s), +{additions}/-{deletions}")
}

fn risk_shape(
    changed_surfaces: &[ChangedSurface],
    capabilities: &ContextCapabilities,
) -> Vec<String> {
    let mut shape = vec![diff_summary(changed_surfaces)];
    shape.push(format!("context tier: {}", capability_tier(capabilities)));
    if capabilities.local_runtime {
        shape.push("local runtime probes available".to_string());
    }
    if capabilities.external_research != Default::default() {
        shape.push(format!(
            "external research policy: {:?}",
            capabilities.external_research
        ));
    }
    shape
}

fn skipped_context(capabilities: &ContextCapabilities) -> Vec<String> {
    let mut skipped = Vec::new();
    if !capabilities.repo_head {
        skipped.push("repo_head".to_string());
    }
    if !capabilities.repo_base {
        skipped.push("repo_base".to_string());
    }
    if !capabilities.local_runtime {
        skipped.push("local_runtime".to_string());
    }
    if !capabilities.remote_runtime {
        skipped.push("remote_runtime".to_string());
    }
    if capabilities.external_research == Default::default() {
        skipped.push("external_research".to_string());
    }
    skipped
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::harness::ExecutionPlan;
    use crate::schema::{
        Change, Diff, ExternalResearchPolicy, FileStatus, ReviewPolicy, Source, SourceKind,
    };

    #[test]
    fn reviewer_plan_records_single_master_diff_understanding() {
        let request = ReviewRequest {
            schema_version: crate::schema::REVIEW_REQUEST_SCHEMA.to_string(),
            request_id: "req-1".to_string(),
            source: Source {
                kind: SourceKind::Fixture,
                external_id: None,
                repo: None,
                uri: None,
                metadata: serde_json::json!({}),
            },
            change: Change {
                title: "change".to_string(),
                description: None,
                base_ref: None,
                head_ref: None,
                head_sha: None,
                diff: Diff {
                    format: "unified".to_string(),
                    body: "diff --git a/src/lib.rs b/src/lib.rs\n".to_string(),
                    digest: None,
                },
                files: vec![ChangedFile {
                    path: "src/lib.rs".to_string(),
                    status: FileStatus::Modified,
                    old_path: None,
                    additions: Some(3),
                    deletions: Some(1),
                }],
            },
            context: Default::default(),
            policy: ReviewPolicy {
                external_research: ExternalResearchPolicy::Forbid,
                ..ReviewPolicy::default()
            },
        };
        let plan = build_reviewer_plan(
            &request,
            &ExecutionPlan {
                harness: "fixture".to_string(),
                command: "fixture".to_string(),
                args: Vec::new(),
                cwd: ".".to_string(),
                timeout_ms: 1000,
                env_allowlist: Vec::new(),
                context_capabilities: ContextCapabilities::from_request(&request),
                prompt_transport: "fixture".to_string(),
                private_material_in_argv: false,
                workspace_mode: "diff_packet".to_string(),
                runtime_transcripts: Vec::new(),
            },
            &ReviewTelemetry {
                model: Some("fixture-model".to_string()),
                ..ReviewTelemetry::default()
            },
        )
        .unwrap();

        assert_eq!(plan.schema_version, REVIEWER_PLAN_SCHEMA);
        assert_eq!(plan.lane_decision.mode, LaneDecisionMode::SingleMaster);
        assert!(plan.child_lanes.is_empty());
        assert_eq!(plan.master_lane.model.as_deref(), Some("fixture-model"));
        assert_eq!(plan.master_lane.allowed_context_tier, "diff_only");
        assert_eq!(
            plan.diff_understanding.changed_surfaces[0].path,
            "src/lib.rs"
        );
        assert!(plan
            .diff_understanding
            .skipped_context
            .contains(&"repo_head".to_string()));
        assert_eq!(
            plan.synthesis.validation_gate,
            "validate_artifact_for_request"
        );
    }
}
