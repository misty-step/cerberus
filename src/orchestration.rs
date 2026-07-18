use anyhow::{bail, Result};
use serde::{Deserialize, Serialize};

use crate::digest::request_digest;
use crate::harness::ExecutionPlan;
use crate::receipt::capability_tier;
use crate::schema::{
    ChangedFile, ContextCapabilities, FileStatus, LifecycleState, Receipt, ReceiptRole,
    ReceiptStatus, ReviewArtifact, ReviewRequest, ReviewTelemetry, RunError,
};
use crate::seat_policy::{
    admit_seat_plan, classify_diff_tier, load_seat_policy, DiffTier, SeatAdmissionVerdict,
    SeatPolicy, SEAT_POLICY_SCHEMA,
};

pub const REVIEWER_PLAN_SCHEMA: &str = "cerberus.reviewer_plan.v1";
pub const REVIEWER_LANE_RECEIPT_SCHEMA: &str = "cerberus.reviewer_lane_receipt.v1";

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
    PlannedChildLanes,
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

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ReviewerLaneReceipt {
    pub schema_version: String,
    pub request_id: String,
    pub lane_id: String,
    pub role: String,
    pub status: ReceiptStatus,
    pub summary: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub transcript_uri: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub artifact_uri: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<RunError>,
}

pub struct ReviewerLaneLaunch<'a> {
    pub request: &'a ReviewRequest,
    pub reviewer_plan: &'a ReviewerPlanReceipt,
    pub lane: &'a ReviewerLanePlan,
}

pub trait ReviewerLaneSubstrate {
    fn launch_reviewer_lane(&self, launch: ReviewerLaneLaunch<'_>) -> Result<ReviewerLaneReceipt>;
}

pub fn launch_planned_child_lanes<S: ReviewerLaneSubstrate>(
    substrate: &S,
    request: &ReviewRequest,
    reviewer_plan: &ReviewerPlanReceipt,
) -> Result<Vec<ReviewerLaneReceipt>> {
    reviewer_plan
        .child_lanes
        .iter()
        .map(|lane| {
            substrate.launch_reviewer_lane(ReviewerLaneLaunch {
                request,
                reviewer_plan,
                lane,
            })
        })
        .collect()
}

pub fn synthesize_lane_receipts_into_artifact(
    artifact: &mut ReviewArtifact,
    lane_receipts: &[ReviewerLaneReceipt],
) -> Result<()> {
    for lane_receipt in lane_receipts {
        if lane_receipt.schema_version != REVIEWER_LANE_RECEIPT_SCHEMA {
            bail!(
                "unsupported reviewer lane receipt schema for {}: {}",
                lane_receipt.lane_id,
                lane_receipt.schema_version
            );
        }
        if lane_receipt.request_id != artifact.request_id {
            bail!(
                "reviewer lane receipt {} request id mismatch: expected {}, got {}",
                lane_receipt.lane_id,
                artifact.request_id,
                lane_receipt.request_id
            );
        }

        artifact.receipts.push(Receipt {
            id: lane_receipt.lane_id.clone(),
            role: ReceiptRole::Reviewer,
            perspective: Some(lane_receipt.role.clone()),
            model: None,
            provider: None,
            harness: Some("reviewer-lane".to_string()),
            status: lane_receipt.status.clone(),
            verdict: None,
            summary: Some(lane_receipt.summary.clone()),
            artifact_digest: None,
            transcript_uri: lane_receipt.transcript_uri.clone(),
            usage: None,
            error: lane_receipt.error.clone(),
        });

        if lane_receipt.status != ReceiptStatus::Completed {
            if artifact.lifecycle_state == LifecycleState::Completed {
                artifact.lifecycle_state = LifecycleState::CompletedDegraded;
            }
            artifact.summary.residual_risk.push(format!(
                "Child reviewer lane {} ({}) ended with status {}; synthesized review may be incomplete.",
                lane_receipt.lane_id,
                lane_receipt.role,
                receipt_status_label(&lane_receipt.status)
            ));
            if let Some(error) = &lane_receipt.error {
                artifact.errors.push(error.clone());
            }
        }
    }
    Ok(())
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

    let seat_policy = load_seat_policy()?;
    let diff_tier = classify_diff_tier(&request.change.files);
    let (lane_decision, child_lanes) = plan_seat_admitted_lanes(
        diff_tier,
        &seat_policy,
        &scope,
        &context_tier,
        &execution_plan.harness,
    )?;

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
        lane_decision,
        master_lane: ReviewerLanePlan {
            id: "lane-master".to_string(),
            role: "master".to_string(),
            objective:
                "Review the change using the declared context and synthesize the final artifact."
                    .to_string(),
            scope,
            allowed_context_tier: context_tier,
            substrate: execution_plan.harness.clone(),
            model: telemetry.model.clone(),
            cost_budget_usd: None,
            stop_condition:
                "Stop after a validated ReviewArtifact.v1 is emitted or the substrate fails."
                    .to_string(),
            expected_output: "ReviewArtifact.v1".to_string(),
        },
        child_lanes,
        synthesis: synthesis_plan_for_tier(diff_tier),
    })
}

/// Build a tier-accurate `SynthesisPlan`. Tier 0 keeps the pre-existing
/// single-master notes; Tier 1 says what actually happened at this point in
/// the pipeline -- floor-satisfying lanes were *planned and admitted*, not
/// launched -- rather than reusing the Tier 0 "no child lanes" language,
/// which reads as contradicting a populated `child_lanes` list.
fn synthesis_plan_for_tier(tier: DiffTier) -> SynthesisPlan {
    match tier {
        DiffTier::Tier0 => SynthesisPlan {
            strategy: "single_master_synthesis".to_string(),
            artifact_contract: "ReviewArtifact.v1".to_string(),
            validation_gate: "validate_artifact_for_request".to_string(),
            notes: vec![
                "Tier 0 diff: the seat-policy floor is empty, so no child lanes were planned or launched in this run.".to_string(),
                "Future child-lane evidence must be captured as ReviewerLaneReceipt.v1, synthesized into the same artifact receipts, and cannot bypass validation.".to_string(),
            ],
        },
        DiffTier::Tier1 => SynthesisPlan {
            strategy: "seat_policy_admitted_planned_lanes".to_string(),
            artifact_contract: "ReviewArtifact.v1".to_string(),
            validation_gate: "validate_artifact_for_request".to_string(),
            notes: vec![
                "Tier 1 diff: seat-policy-floor-satisfying child lanes were planned and admitted (see child_lanes and lane_decision), but launch remains disabled until the reviewer-lane substrate lands (see launch_planned_child_lanes).".to_string(),
                "Future child-lane evidence must be captured as ReviewerLaneReceipt.v1, synthesized into the same artifact receipts, and cannot bypass validation.".to_string(),
            ],
        },
    }
}

/// Build the declared lane decision + child-lane set for one review, and
/// admit it against the seat-policy floor (ADR 0004). On Tier 0 the floor
/// is empty and the run stays single-master. On Tier 1, this constructs one
/// planned (not yet launched -- see \`launch_planned_child_lanes\`) lane per
/// required floor seat, naming only the seat's role label; it never fills
/// in a model (\`model: None\`), matching the ADR's "the master decides the
/// model" rule.
///
/// Admission is re-checked here as a defense-in-depth self-check: this
/// function is currently the only "master" that declares lanes (the
/// reviewer-lane substrate that would let an external master submit its
/// own plan has not landed yet), so a rejection here means a bug in this
/// function itself, not an external caller -- fail closed rather than
/// silently emit a floor-violating plan.
fn plan_seat_admitted_lanes(
    tier: DiffTier,
    seat_policy: &SeatPolicy,
    scope: &[String],
    context_tier: &str,
    harness: &str,
) -> Result<(LaneDecision, Vec<ReviewerLanePlan>)> {
    match tier {
        DiffTier::Tier0 => Ok((
            LaneDecision {
                mode: LaneDecisionMode::SingleMaster,
                reason: "Tier 0 diff (no meaningful content change; see seat_policy::classify_diff_tier): the seat-policy floor is empty, so only the master lane runs.".to_string(),
                stop_condition: "Emit exactly one ReviewArtifact.v1 candidate and pass validate_artifact_for_request, or fail closed.".to_string(),
                cost_budget_usd: None,
            },
            Vec::new(),
        )),
        DiffTier::Tier1 => {
            let planned: Vec<ReviewerLanePlan> = seat_policy
                .tier1_floor
                .seats
                .iter()
                .map(|seat| ReviewerLanePlan {
                    id: format!("lane-{}", sanitize_lane_id(&seat.role)),
                    role: seat.role.clone(),
                    objective: "Planned to satisfy the Tier 1 seat-policy floor; the master reviewer authors this lane's actual prompt, scope, and model at launch time.".to_string(),
                    scope: scope.to_vec(),
                    allowed_context_tier: context_tier.to_string(),
                    substrate: harness.to_string(),
                    model: None,
                    cost_budget_usd: None,
                    stop_condition: "Return one ReviewerLaneReceipt.v1 with evidence or a fail-closed error status.".to_string(),
                    expected_output: "ReviewerLaneReceipt.v1".to_string(),
                })
                .collect();

            match admit_seat_plan(tier, &seat_policy.tier1_floor, &planned) {
                SeatAdmissionVerdict::Accepted => {}
                SeatAdmissionVerdict::Rejected { missing_roles } => bail!(
                    "seat policy admission rejected the planned Tier 1 lane set: missing required role(s) {}",
                    missing_roles.join(", ")
                ),
            }

            Ok((
                LaneDecision {
                    mode: LaneDecisionMode::PlannedChildLanes,
                    reason: format!(
                        "Tier 1 diff admitted against the seat-policy floor ({} required seat(s), {SEAT_POLICY_SCHEMA}); child lane launch remains disabled until the reviewer-lane substrate lands (see launch_planned_child_lanes).",
                        seat_policy.tier1_floor.seat_count
                    ),
                    stop_condition: "Emit exactly one ReviewArtifact.v1 candidate and pass validate_artifact_for_request, or fail closed.".to_string(),
                    cost_budget_usd: None,
                },
                planned,
            ))
        }
    }
}

/// Delegates to `crate::request::sanitize_id` (the same lane/request id
/// normalization already used for request ids) rather than reimplementing
/// the same "replace anything non-alphanumeric/dash/underscore with a
/// dash" rule a second time.
fn sanitize_lane_id(role: &str) -> String {
    crate::request::sanitize_id(role)
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

fn receipt_status_label(status: &ReceiptStatus) -> &'static str {
    match status {
        ReceiptStatus::Completed => "completed",
        ReceiptStatus::Timeout => "timeout",
        ReceiptStatus::Error => "error",
        ReceiptStatus::Skipped => "skipped",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::digest::request_digest;
    use crate::harness::ExecutionPlan;
    use crate::schema::{
        Change, Coverage, Diff, ErrorScope, ExternalResearchPolicy, FileStatus, LifecycleState,
        ReceiptRole, ReviewArtifact, ReviewPolicy, RunInfo, Source, SourceKind, Summary, Verdict,
        REVIEW_ARTIFACT_SCHEMA,
    };
    use crate::validation::validate_artifact_for_request;

    #[test]
    fn reviewer_plan_plans_seat_policy_floor_lanes_for_tier1_diff() {
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

        let seat_policy = crate::seat_policy::load_seat_policy().unwrap();

        assert_eq!(plan.schema_version, REVIEWER_PLAN_SCHEMA);
        // A Modified file is a meaningful (Tier 1) diff: the seat-policy
        // floor applies, so the plan names one lane per required role.
        assert_eq!(plan.lane_decision.mode, LaneDecisionMode::PlannedChildLanes);
        assert_eq!(plan.child_lanes.len(), seat_policy.tier1_floor.seat_count);
        let declared_roles: std::collections::HashSet<&str> = plan
            .child_lanes
            .iter()
            .map(|lane| lane.role.as_str())
            .collect();
        let floor_roles: std::collections::HashSet<&str> = seat_policy
            .tier1_floor
            .seats
            .iter()
            .map(|seat| seat.role.as_str())
            .collect();
        assert_eq!(declared_roles, floor_roles);
        // Rust never picks a model for a planned lane -- the master decides
        // at launch time.
        assert!(plan.child_lanes.iter().all(|lane| lane.model.is_none()));
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

    #[test]
    fn reviewer_plan_stays_single_master_for_tier0_diff() {
        let request = ReviewRequest {
            schema_version: crate::schema::REVIEW_REQUEST_SCHEMA.to_string(),
            request_id: "req-tier0".to_string(),
            source: Source {
                kind: SourceKind::Fixture,
                external_id: None,
                repo: None,
                uri: None,
                metadata: serde_json::json!({}),
            },
            change: Change {
                title: "rename only".to_string(),
                description: None,
                base_ref: None,
                head_ref: None,
                head_sha: None,
                diff: Diff {
                    format: "unified".to_string(),
                    body: "diff --git a/src/old.rs b/src/new.rs\nsimilarity index 100%\nrename from src/old.rs\nrename to src/new.rs\n".to_string(),
                    digest: None,
                },
                files: vec![ChangedFile {
                    path: "src/new.rs".to_string(),
                    status: FileStatus::Renamed,
                    old_path: Some("src/old.rs".to_string()),
                    additions: Some(0),
                    deletions: Some(0),
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
            &ReviewTelemetry::default(),
        )
        .unwrap();

        assert_eq!(plan.lane_decision.mode, LaneDecisionMode::SingleMaster);
        assert!(plan.child_lanes.is_empty());
    }

    #[test]
    fn lane_substrate_launches_arbitrary_planned_roles() {
        let request = request();
        let mut plan =
            build_reviewer_plan(&request, &execution_plan(&request), &Default::default()).unwrap();
        plan.lane_decision.mode = LaneDecisionMode::PlannedChildLanes;
        // Replace (not append to) the seat-policy floor's default planned
        // lanes: this test proves the substrate can launch an arbitrary
        // master-declared role, not just the floor's four -- no static
        // roster in Rust (AGENTS.md red line 1).
        plan.child_lanes = vec![ReviewerLanePlan {
            id: "lane-model-boundary".to_string(),
            role: "model-boundary-risk".to_string(),
            objective: "Look for deterministic heuristics where model judgment belongs."
                .to_string(),
            scope: vec!["src/orchestration.rs".to_string()],
            allowed_context_tier: "repo_base_and_head".to_string(),
            substrate: "fixture-lane".to_string(),
            model: Some("fixture-lane-model".to_string()),
            cost_budget_usd: Some("0.01".to_string()),
            stop_condition: "Return one receipt with evidence or skipped status.".to_string(),
            expected_output: "ReviewerLaneReceipt.v1".to_string(),
        }];

        let receipts =
            launch_planned_child_lanes(&RecordingLaneSubstrate, &request, &plan).unwrap();

        assert_eq!(receipts.len(), 1);
        assert_eq!(receipts[0].schema_version, REVIEWER_LANE_RECEIPT_SCHEMA);
        assert_eq!(receipts[0].lane_id, "lane-model-boundary");
        assert_eq!(receipts[0].role, "model-boundary-risk");
        assert_eq!(receipts[0].status, ReceiptStatus::Completed);
        assert_eq!(receipts[0].request_id, request.request_id);
    }

    #[test]
    fn no_lane_synthesis_leaves_single_master_artifact_unchanged() {
        let request = request();
        let mut artifact = artifact_for(&request);
        let before = artifact.clone();

        synthesize_lane_receipts_into_artifact(&mut artifact, &[]).unwrap();

        assert_eq!(artifact, before);
        validate_artifact_for_request(&artifact, &request).unwrap();
    }

    #[test]
    fn one_lane_synthesis_records_dynamic_lane_as_generic_reviewer_receipt() {
        let request = request();
        let mut artifact = artifact_for(&request);
        let lane_receipt = lane_receipt(
            "lane-model-boundary",
            "model-boundary-risk",
            ReceiptStatus::Completed,
            None,
        );

        synthesize_lane_receipts_into_artifact(&mut artifact, &[lane_receipt]).unwrap();

        assert_eq!(artifact.lifecycle_state, LifecycleState::Completed);
        assert!(artifact.errors.is_empty());
        assert_eq!(artifact.receipts.len(), 1);

        let receipt = &artifact.receipts[0];
        assert_eq!(receipt.id, "lane-model-boundary");
        assert_eq!(receipt.role, ReceiptRole::Reviewer);
        assert_eq!(receipt.perspective.as_deref(), Some("model-boundary-risk"));
        assert_eq!(receipt.harness.as_deref(), Some("reviewer-lane"));
        assert_eq!(receipt.status, ReceiptStatus::Completed);
        assert_eq!(
            receipt.summary.as_deref(),
            Some("lane completed with grounded evidence")
        );
        assert_eq!(
            receipt.transcript_uri.as_deref(),
            Some("fixture://lane-model-boundary/transcript")
        );
        assert!(receipt.error.is_none());
        validate_artifact_for_request(&artifact, &request).unwrap();
    }

    #[test]
    fn failed_lane_synthesis_degrades_completed_artifact() {
        let request = request();
        let mut artifact = artifact_for(&request);
        let lane_error = RunError {
            scope: ErrorScope::Reviewer,
            code: "lane_failed".to_string(),
            message: "fixture lane could not complete".to_string(),
            retryable: true,
        };
        let lane_receipt = lane_receipt(
            "lane-security",
            "security-focused-review",
            ReceiptStatus::Error,
            Some(lane_error.clone()),
        );

        synthesize_lane_receipts_into_artifact(&mut artifact, &[lane_receipt]).unwrap();

        assert_eq!(artifact.lifecycle_state, LifecycleState::CompletedDegraded);
        assert_eq!(artifact.receipts.len(), 1);
        assert_eq!(artifact.receipts[0].status, ReceiptStatus::Error);
        assert_eq!(artifact.receipts[0].error.as_ref(), Some(&lane_error));
        assert_eq!(artifact.errors, vec![lane_error]);
        assert!(artifact.summary.residual_risk.iter().any(|risk| {
            risk.contains("lane-security")
                && risk.contains("security-focused-review")
                && risk.contains("error")
        }));
        validate_artifact_for_request(&artifact, &request).unwrap();
    }

    #[test]
    fn lane_synthesis_rejects_mismatched_request_id() {
        let request = request();
        let mut artifact = artifact_for(&request);
        let mut lane_receipt = lane_receipt(
            "lane-other-request",
            "model-boundary-risk",
            ReceiptStatus::Completed,
            None,
        );
        lane_receipt.request_id = "other-req".to_string();

        let error =
            synthesize_lane_receipts_into_artifact(&mut artifact, &[lane_receipt]).unwrap_err();

        assert!(error.to_string().contains("request id mismatch"));
        assert!(artifact.receipts.is_empty());
        assert_eq!(artifact.lifecycle_state, LifecycleState::Completed);
        validate_artifact_for_request(&artifact, &request).unwrap();
    }

    struct RecordingLaneSubstrate;

    impl ReviewerLaneSubstrate for RecordingLaneSubstrate {
        fn launch_reviewer_lane(
            &self,
            launch: ReviewerLaneLaunch<'_>,
        ) -> Result<ReviewerLaneReceipt> {
            assert_eq!(launch.reviewer_plan.request_id, launch.request.request_id);
            assert_eq!(launch.lane.role, "model-boundary-risk");
            Ok(ReviewerLaneReceipt {
                schema_version: REVIEWER_LANE_RECEIPT_SCHEMA.to_string(),
                request_id: launch.request.request_id.clone(),
                lane_id: launch.lane.id.clone(),
                role: launch.lane.role.clone(),
                status: ReceiptStatus::Completed,
                summary: format!("launched {}", launch.lane.objective),
                transcript_uri: Some("fixture://lane-transcript".to_string()),
                artifact_uri: None,
                error: None,
            })
        }
    }

    fn request() -> ReviewRequest {
        ReviewRequest {
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
        }
    }

    fn execution_plan(request: &ReviewRequest) -> ExecutionPlan {
        ExecutionPlan {
            harness: "fixture".to_string(),
            command: "fixture".to_string(),
            args: Vec::new(),
            cwd: ".".to_string(),
            timeout_ms: 1000,
            env_allowlist: Vec::new(),
            context_capabilities: ContextCapabilities::from_request(request),
            prompt_transport: "fixture".to_string(),
            private_material_in_argv: false,
            workspace_mode: "diff_packet".to_string(),
            runtime_transcripts: Vec::new(),
        }
    }

    fn artifact_for(request: &ReviewRequest) -> ReviewArtifact {
        ReviewArtifact {
            schema_version: REVIEW_ARTIFACT_SCHEMA.to_string(),
            artifact_id: "art-1".to_string(),
            request_id: request.request_id.clone(),
            request_digest: request_digest(request).unwrap(),
            lifecycle_state: LifecycleState::Completed,
            verdict: Verdict::Pass,
            context_capabilities: ContextCapabilities::from_request(request),
            summary: Summary {
                title: "clean".to_string(),
                body: "No blocking issues.".to_string(),
                analysis: String::new(),
                residual_risk: Vec::new(),
            },
            findings: Vec::new(),
            comments: Vec::new(),
            suggested_fixes: Vec::new(),
            citations: Vec::new(),
            receipts: Vec::new(),
            run: RunInfo {
                engine_version: "test".to_string(),
                config_digest: "sha256:test".to_string(),
                started_at: "2026-07-01T00:00:00Z".to_string(),
                finished_at: "2026-07-01T00:00:01Z".to_string(),
                duration_ms: 1,
                cost_usd: None,
                coverage: Coverage {
                    files_reviewed: vec!["src/lib.rs".to_string()],
                    files_with_findings: Vec::new(),
                },
            },
            errors: Vec::new(),
        }
    }

    fn lane_receipt(
        lane_id: &str,
        role: &str,
        status: ReceiptStatus,
        error: Option<RunError>,
    ) -> ReviewerLaneReceipt {
        ReviewerLaneReceipt {
            schema_version: REVIEWER_LANE_RECEIPT_SCHEMA.to_string(),
            request_id: "req-1".to_string(),
            lane_id: lane_id.to_string(),
            role: role.to_string(),
            status,
            summary: "lane completed with grounded evidence".to_string(),
            transcript_uri: Some(format!("fixture://{lane_id}/transcript")),
            artifact_uri: None,
            error,
        }
    }
}
