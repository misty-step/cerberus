//! Declarative seat-policy admission
//! (`docs/adr/0004-declarative-seat-policy-not-static-roster.md`).
//!
//! This module enforces *coverage*, never *content*: whether the master
//! reviewer's declared lane set names the required roles, and whether the
//! mandatory Factory model-vs-heuristic dimension is present, is a
//! decidable oracle question (ADR 0003: "can a non-AI oracle decide
//! pass/fail with certainty?"). What each lane's system prompt says, which
//! model it uses, and how good its findings are stays model judgment --
//! this module never authors a persona, a prompt, or a fixed model choice.
//! See ADR 0004's residual-risk paragraph: policy data may name required
//! roles/dimensions and a count, and nothing else.

use std::collections::HashSet;

use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};

use crate::orchestration::ReviewerLanePlan;
use crate::schema::{ChangedFile, FileStatus};

pub const SEAT_POLICY_SCHEMA: &str = "cerberus.seat_policy.v1";

/// Trusted, versioned, repo-owned seat-policy data (ADR 0004 decision 2),
/// embedded at compile time from a real, diffable, reviewable JSON file --
/// the same trusted-data spirit as `config/omp-version.json`'s runtime-read
/// pin, without adding a new runtime file-I/O failure mode to every
/// review's admission path (this policy has no "bump without a rebuild"
/// requirement the way a substrate version pin does).
const SEAT_POLICY_JSON: &str = include_str!("../config/seat_policy.json");

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct SeatPolicy {
    pub schema_version: String,
    pub tier1_floor: Tier1Floor,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct Tier1Floor {
    pub seat_count: usize,
    pub seats: Vec<RequiredSeat>,
}

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq, Eq)]
pub struct RequiredSeat {
    /// A coverage-area label (e.g. "security-and-trust-boundary"). Data
    /// only -- never a persona identity or system prompt. The master
    /// reviewer still authors the actual lane prompt/scope/model for this
    /// role at launch time; Rust only checks that a declared lane carries
    /// this role label.
    pub role: String,
    pub dimension: SeatDimension,
}

/// The Factory model-vs-heuristic dimension (VISION.md's "named dimensions
/// guide the master; they do not become hardcoded personas... including
/// the mandatory Factory dimension"): whether a seat is another model call
/// or a deterministic tool/heuristic. ADR 0004 requires at least one
/// mandatory Tier 1 seat carry `HeuristicTool`.
#[derive(Debug, Clone, Copy, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum SeatDimension {
    ModelJudgment,
    HeuristicTool,
}

/// Parse and sanity-check the embedded seat policy. Fails closed rather
/// than silently dropping the floor if the embedded data is malformed,
/// internally inconsistent, or missing the mandatory Factory dimension --
/// all build-time bugs, not runtime conditions, but surfacing them as a
/// `Result` keeps this on the same fail-closed path as
/// `build_reviewer_plan`'s other fallible steps instead of panicking.
pub fn load_seat_policy() -> Result<SeatPolicy> {
    let policy: SeatPolicy = serde_json::from_str(SEAT_POLICY_JSON)
        .context("parse embedded seat policy (config/seat_policy.json)")?;
    validate_seat_policy(policy)
}

/// Sanity-check a parsed seat policy: schema version, internal
/// seat_count/seats.len() consistency, role-label uniqueness (a duplicated
/// role would let seat_count overstate real coverage without tripping any
/// other check), and presence of the mandatory Factory dimension. Split out
/// from `load_seat_policy` so it can be unit-tested directly against
/// hand-built `SeatPolicy` values, not only the one embedded config.
fn validate_seat_policy(policy: SeatPolicy) -> Result<SeatPolicy> {
    if policy.schema_version != SEAT_POLICY_SCHEMA {
        bail!(
            "unsupported seat policy schema_version {} (expected {SEAT_POLICY_SCHEMA})",
            policy.schema_version
        );
    }
    if policy.tier1_floor.seats.len() != policy.tier1_floor.seat_count {
        bail!(
            "seat policy tier1_floor.seat_count ({}) does not match tier1_floor.seats.len() ({})",
            policy.tier1_floor.seat_count,
            policy.tier1_floor.seats.len()
        );
    }
    let mut seen_roles: HashSet<&str> = HashSet::new();
    for seat in &policy.tier1_floor.seats {
        if !seen_roles.insert(seat.role.as_str()) {
            bail!(
                "seat policy tier1_floor.seats contains a duplicate role {:?}; each required seat must name a distinct role",
                seat.role
            );
        }
    }
    if !policy
        .tier1_floor
        .seats
        .iter()
        .any(|seat| seat.dimension == SeatDimension::HeuristicTool)
    {
        bail!(
            "seat policy tier1_floor is missing the mandatory Factory model-vs-heuristic \
             dimension (no seat is tagged heuristic_tool); see ADR 0004"
        );
    }
    Ok(policy)
}

/// Deterministic Tier 0 / Tier 1 diff classification (ADR 0004 decision 1).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DiffTier {
    /// No meaningful diff: no seats required.
    Tier0,
    /// A meaningful diff: the Tier 1 seat-policy floor applies.
    Tier1,
}

/// Classify a changed-file set as Tier 0 or Tier 1. This is an oracle
/// question (ADR 0003): the diff either changed reviewable content or it
/// did not, decidable purely from `ChangedFile` shape, never a model call.
///
/// Tier 0 iff the change touches zero files, or every changed file is a
/// pure rename/copy with zero content delta (`FileStatus::Renamed` or
/// `FileStatus::Copied` with `additions == Some(0)` and
/// `deletions == Some(0)`) -- i.e. a path moved or was duplicated without a
/// single line of content changing. Any `Added`/`Modified`/`Removed` file,
/// or a `Renamed`/`Copied` file with nonzero or unknown (`None`) line
/// counts, makes the whole request Tier 1.
///
/// This deliberately does not attempt whitespace-only content
/// classification: `ChangedFile` carries aggregate line counts, not diff
/// content, and inferring "whitespace-only" from `+N/-N` alone is
/// unreliable (a single-character edit inside a line still reports
/// `+1/-1`, identical in shape to a real one-line content change). A
/// future risk classifier that *adds* seats above the floor may reach for
/// richer signals (e.g. the raw diff body); this floor classifier stays
/// conservative and exact so it never wrongly waves through a real change
/// as Tier 0.
pub fn classify_diff_tier(files: &[ChangedFile]) -> DiffTier {
    if files.is_empty() || files.iter().all(is_content_free_rename) {
        DiffTier::Tier0
    } else {
        DiffTier::Tier1
    }
}

fn is_content_free_rename(file: &ChangedFile) -> bool {
    matches!(file.status, FileStatus::Renamed | FileStatus::Copied)
        && file.additions == Some(0)
        && file.deletions == Some(0)
}

/// Deterministic admission verdict (ADR 0004 decision 4): the master may
/// add lanes beyond the floor; it may never declare fewer required roles
/// than the floor on a Tier 1 diff.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SeatAdmissionVerdict {
    Accepted,
    Rejected { missing_roles: Vec<String> },
}

/// Check the master's *declared* child-lane role set against the policy
/// floor. Tier 0 has an empty floor and always accepts. Tier 1 requires
/// the declared roles (by label, matching `ReviewerLanePlan::role`) to be a
/// superset of `floor.seats`'s roles -- a set-superset comparison, which is
/// an oracle question (ADR 0004 decision 4), not a quality judgment. This
/// function never inspects a lane's prompt, scope, or model -- only its
/// declared role label, which the master itself writes at runtime.
pub fn admit_seat_plan(
    tier: DiffTier,
    floor: &Tier1Floor,
    declared_child_lanes: &[ReviewerLanePlan],
) -> SeatAdmissionVerdict {
    if tier == DiffTier::Tier0 {
        return SeatAdmissionVerdict::Accepted;
    }
    let declared_roles: HashSet<&str> = declared_child_lanes
        .iter()
        .map(|lane| lane.role.as_str())
        .collect();
    let missing_roles: Vec<String> = floor
        .seats
        .iter()
        .filter(|seat| !declared_roles.contains(seat.role.as_str()))
        .map(|seat| seat.role.clone())
        .collect();
    if missing_roles.is_empty() {
        SeatAdmissionVerdict::Accepted
    } else {
        SeatAdmissionVerdict::Rejected { missing_roles }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn changed(
        path: &str,
        status: FileStatus,
        additions: Option<u32>,
        deletions: Option<u32>,
    ) -> ChangedFile {
        ChangedFile {
            path: path.to_string(),
            status,
            old_path: None,
            additions,
            deletions,
        }
    }

    fn lane(role: &str) -> ReviewerLanePlan {
        ReviewerLanePlan {
            id: format!("lane-{role}"),
            role: role.to_string(),
            objective: "test".to_string(),
            scope: Vec::new(),
            allowed_context_tier: "diff_only".to_string(),
            substrate: "fixture".to_string(),
            model: None,
            cost_budget_usd: None,
            stop_condition: "test".to_string(),
            expected_output: "ReviewerLaneReceipt.v1".to_string(),
        }
    }

    #[test]
    fn embedded_seat_policy_loads_and_carries_the_mandatory_heuristic_dimension() {
        let policy = load_seat_policy().unwrap();
        assert_eq!(policy.schema_version, SEAT_POLICY_SCHEMA);
        assert_eq!(policy.tier1_floor.seat_count, 4);
        assert_eq!(policy.tier1_floor.seats.len(), 4);
        assert!(policy
            .tier1_floor
            .seats
            .iter()
            .any(|seat| seat.dimension == SeatDimension::HeuristicTool));
    }

    #[test]
    fn validate_seat_policy_rejects_duplicate_roles() {
        let policy = SeatPolicy {
            schema_version: SEAT_POLICY_SCHEMA.to_string(),
            tier1_floor: Tier1Floor {
                seat_count: 2,
                seats: vec![
                    RequiredSeat {
                        role: "duplicate-role".to_string(),
                        dimension: SeatDimension::ModelJudgment,
                    },
                    RequiredSeat {
                        role: "duplicate-role".to_string(),
                        dimension: SeatDimension::HeuristicTool,
                    },
                ],
            },
        };
        let error = validate_seat_policy(policy).unwrap_err();
        assert!(error.to_string().contains("duplicate role"));
    }

    #[test]
    fn validate_seat_policy_rejects_missing_heuristic_dimension() {
        let policy = SeatPolicy {
            schema_version: SEAT_POLICY_SCHEMA.to_string(),
            tier1_floor: Tier1Floor {
                seat_count: 1,
                seats: vec![RequiredSeat {
                    role: "only-model-seat".to_string(),
                    dimension: SeatDimension::ModelJudgment,
                }],
            },
        };
        let error = validate_seat_policy(policy).unwrap_err();
        assert!(error.to_string().contains("heuristic_tool"));
    }

    #[test]
    fn validate_seat_policy_rejects_seat_count_mismatch() {
        let policy = SeatPolicy {
            schema_version: SEAT_POLICY_SCHEMA.to_string(),
            tier1_floor: Tier1Floor {
                seat_count: 2,
                seats: vec![RequiredSeat {
                    role: "only-one-seat".to_string(),
                    dimension: SeatDimension::HeuristicTool,
                }],
            },
        };
        let error = validate_seat_policy(policy).unwrap_err();
        assert!(error.to_string().contains("seat_count"));
    }

    #[test]
    fn empty_changeset_classifies_as_tier0() {
        assert_eq!(classify_diff_tier(&[]), DiffTier::Tier0);
    }

    #[test]
    fn pure_rename_with_zero_delta_classifies_as_tier0() {
        let files = vec![changed("b.rs", FileStatus::Renamed, Some(0), Some(0))];
        assert_eq!(classify_diff_tier(&files), DiffTier::Tier0);
    }

    #[test]
    fn pure_copy_with_zero_delta_classifies_as_tier0() {
        let files = vec![changed("b.rs", FileStatus::Copied, Some(0), Some(0))];
        assert_eq!(classify_diff_tier(&files), DiffTier::Tier0);
    }

    #[test]
    fn modified_file_classifies_as_tier1() {
        let files = vec![changed("a.rs", FileStatus::Modified, Some(3), Some(1))];
        assert_eq!(classify_diff_tier(&files), DiffTier::Tier1);
    }

    #[test]
    fn rename_with_nonzero_delta_classifies_as_tier1() {
        let files = vec![changed("b.rs", FileStatus::Renamed, Some(1), Some(0))];
        assert_eq!(classify_diff_tier(&files), DiffTier::Tier1);
    }

    #[test]
    fn rename_with_unknown_delta_classifies_as_tier1() {
        let files = vec![changed("b.rs", FileStatus::Renamed, None, None)];
        assert_eq!(classify_diff_tier(&files), DiffTier::Tier1);
    }

    #[test]
    fn mixed_changeset_with_one_real_edit_classifies_as_tier1() {
        let files = vec![
            changed("b.rs", FileStatus::Renamed, Some(0), Some(0)),
            changed("a.rs", FileStatus::Added, Some(10), Some(0)),
        ];
        assert_eq!(classify_diff_tier(&files), DiffTier::Tier1);
    }

    #[test]
    fn tier0_admission_accepts_with_no_declared_lanes() {
        let policy = load_seat_policy().unwrap();
        let verdict = admit_seat_plan(DiffTier::Tier0, &policy.tier1_floor, &[]);
        assert_eq!(verdict, SeatAdmissionVerdict::Accepted);
    }

    #[test]
    fn tier1_admission_accepts_declared_superset_of_floor() {
        let policy = load_seat_policy().unwrap();
        let mut declared: Vec<ReviewerLanePlan> = policy
            .tier1_floor
            .seats
            .iter()
            .map(|seat| lane(&seat.role))
            .collect();
        // The master may add lanes beyond the floor.
        declared.push(lane("extra-risk-triggered-lane"));
        let verdict = admit_seat_plan(DiffTier::Tier1, &policy.tier1_floor, &declared);
        assert_eq!(verdict, SeatAdmissionVerdict::Accepted);
    }

    #[test]
    fn tier1_admission_rejects_when_declared_lanes_undershoot_the_floor() {
        let policy = load_seat_policy().unwrap();
        // Drop the last required role.
        let declared: Vec<ReviewerLanePlan> = policy
            .tier1_floor
            .seats
            .iter()
            .take(policy.tier1_floor.seats.len() - 1)
            .map(|seat| lane(&seat.role))
            .collect();
        let verdict = admit_seat_plan(DiffTier::Tier1, &policy.tier1_floor, &declared);
        match verdict {
            SeatAdmissionVerdict::Rejected { missing_roles } => {
                assert_eq!(missing_roles.len(), 1);
                assert_eq!(
                    missing_roles[0],
                    policy.tier1_floor.seats.last().unwrap().role
                );
            }
            SeatAdmissionVerdict::Accepted => {
                panic!("expected rejection for an undershot lane set")
            }
        }
    }

    #[test]
    fn tier1_admission_rejects_empty_declared_lanes() {
        let policy = load_seat_policy().unwrap();
        let verdict = admit_seat_plan(DiffTier::Tier1, &policy.tier1_floor, &[]);
        match verdict {
            SeatAdmissionVerdict::Rejected { missing_roles } => {
                assert_eq!(missing_roles.len(), policy.tier1_floor.seats.len());
            }
            SeatAdmissionVerdict::Accepted => {
                panic!("expected rejection for zero declared lanes on Tier 1")
            }
        }
    }
}
