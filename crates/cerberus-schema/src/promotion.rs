use crate::{ReviewConfig, SchemaError, Verdict};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

pub const REVIEWER_CONFIG_PACKET_VERSION: &str = "reviewer-config-packet.v1";
pub const REVIEWER_CONFIG_IMPORT_REPORT_VERSION: &str = "reviewer-config-import-report.v1";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ReviewerConfigPacket {
    pub schema_version: String,
    pub packet_id: String,
    pub producer: ReviewerConfigProducer,
    pub benchmark: ReviewerConfigBenchmark,
    pub promotion: PromotionGate,
    pub rollback: RollbackMetadata,
    pub cost: CostEnvelope,
    pub harnesses: Vec<ReviewerHarnessMetadata>,
    pub models: Vec<ReviewerModelMetadata>,
    pub prompt_hashes: BTreeMap<String, String>,
    pub config_hash: String,
    pub config: ReviewConfig,
}

impl ReviewerConfigPacket {
    pub fn validate(&self) -> Result<(), SchemaError> {
        expect_version(
            "schema_version",
            &self.schema_version,
            REVIEWER_CONFIG_PACKET_VERSION,
        )?;
        non_empty("packet_id", &self.packet_id)?;
        self.producer.validate()?;
        self.benchmark.validate()?;
        self.promotion.validate()?;
        self.rollback.validate()?;
        self.cost.validate()?;
        if self.harnesses.is_empty() {
            return Err(SchemaError::Missing { field: "harnesses" });
        }
        let mut harness_ids = BTreeSet::new();
        for harness in &self.harnesses {
            harness.validate()?;
            if !harness_ids.insert(harness.harness_id.as_str()) {
                return Err(SchemaError::Inconsistent {
                    field: "harnesses.harness_id",
                });
            }
        }
        if self.models.is_empty() {
            return Err(SchemaError::Missing { field: "models" });
        }
        if self.prompt_hashes.is_empty() {
            return Err(SchemaError::Missing {
                field: "prompt_hashes",
            });
        }
        for (name, hash) in &self.prompt_hashes {
            non_empty("prompt_hashes.key", name)?;
            non_empty("prompt_hashes.value", hash)?;
        }
        non_empty("config_hash", &self.config_hash)?;
        self.config.validate()?;
        let config_by_reviewer = self
            .config
            .reviewers
            .iter()
            .map(|reviewer| (reviewer.id.as_str(), reviewer))
            .collect::<BTreeMap<_, _>>();
        let config_reviewer_ids = config_by_reviewer.keys().copied().collect::<BTreeSet<_>>();
        let mut model_reviewer_ids = BTreeSet::new();
        for model in &self.models {
            model.validate()?;
            let Some(config_reviewer) = config_by_reviewer.get(model.reviewer_id.as_str()) else {
                return Err(SchemaError::Mismatch {
                    field: "models.reviewer_id",
                    expected: "reviewer id present in config.reviewers".to_string(),
                    actual: model.reviewer_id.clone(),
                });
            };
            if !harness_ids.contains(model.harness_id.as_str()) {
                return Err(SchemaError::Mismatch {
                    field: "models.harness_id",
                    expected: "harness id present in harnesses".to_string(),
                    actual: model.harness_id.clone(),
                });
            }
            let expected_model = format!("{}:{}", model.provider, model.model);
            if config_reviewer.model != expected_model {
                return Err(SchemaError::Mismatch {
                    field: "models.model",
                    expected: config_reviewer.model.clone(),
                    actual: expected_model,
                });
            }
            let Some(expected_prompt_hash) = self.prompt_hashes.get(model.reviewer_id.as_str())
            else {
                return Err(SchemaError::Missing {
                    field: "prompt_hashes.reviewer_id",
                });
            };
            if model.prompt_hash != *expected_prompt_hash {
                return Err(SchemaError::Mismatch {
                    field: "models.prompt_hash",
                    expected: expected_prompt_hash.clone(),
                    actual: model.prompt_hash.clone(),
                });
            };
            if !model_reviewer_ids.insert(model.reviewer_id.as_str()) {
                return Err(SchemaError::Inconsistent {
                    field: "models.reviewer_id",
                });
            }
        }
        if model_reviewer_ids != config_reviewer_ids {
            return Err(SchemaError::Inconsistent {
                field: "models.reviewer_id",
            });
        }
        for name in self.prompt_hashes.keys() {
            if !config_reviewer_ids.contains(name.as_str()) {
                return Err(SchemaError::Mismatch {
                    field: "prompt_hashes.key",
                    expected: "reviewer id present in config.reviewers".to_string(),
                    actual: name.clone(),
                });
            }
        }
        if !self.producer.sandbox_only && self.producer.signature.is_none() {
            return Err(SchemaError::Missing {
                field: "producer.signature",
            });
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReviewerConfigProducer {
    pub system: String,
    pub delivery_id: String,
    pub generated_at: String,
    #[serde(default)]
    pub sandbox_only: bool,
    #[serde(default)]
    pub signature: Option<PacketSignature>,
}

impl ReviewerConfigProducer {
    fn validate(&self) -> Result<(), SchemaError> {
        non_empty("producer.system", &self.system)?;
        non_empty("producer.delivery_id", &self.delivery_id)?;
        non_empty("producer.generated_at", &self.generated_at)?;
        if let Some(signature) = &self.signature {
            signature.validate()?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct PacketSignature {
    pub key_id: String,
    pub signature: String,
}

impl PacketSignature {
    fn validate(&self) -> Result<(), SchemaError> {
        non_empty("signature.key_id", &self.key_id)?;
        non_empty("signature.signature", &self.signature)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ReviewerConfigBenchmark {
    pub benchmark_id: String,
    pub suite_id: String,
    pub arena_version: String,
    pub run_id: String,
    pub task_count: u64,
    pub score_distribution: ScoreDistribution,
}

impl ReviewerConfigBenchmark {
    fn validate(&self) -> Result<(), SchemaError> {
        non_empty("benchmark.benchmark_id", &self.benchmark_id)?;
        non_empty("benchmark.suite_id", &self.suite_id)?;
        non_empty("benchmark.arena_version", &self.arena_version)?;
        non_empty("benchmark.run_id", &self.run_id)?;
        if self.task_count == 0 {
            return Err(SchemaError::Missing {
                field: "benchmark.task_count",
            });
        }
        self.score_distribution.validate()
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ScoreDistribution {
    pub min: f64,
    pub mean: f64,
    pub median: f64,
    pub max: f64,
    #[serde(default)]
    pub certified_trials: u64,
}

impl ScoreDistribution {
    fn validate(&self) -> Result<(), SchemaError> {
        expect_range("score.min", self.min, 0.0, 1.0)?;
        expect_range("score.mean", self.mean, 0.0, 1.0)?;
        expect_range("score.median", self.median, 0.0, 1.0)?;
        expect_range("score.max", self.max, 0.0, 1.0)?;
        if self.min > self.mean
            || self.mean > self.max
            || self.min > self.median
            || self.median > self.max
        {
            return Err(SchemaError::Inconsistent {
                field: "score_distribution",
            });
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PromotionGate {
    pub status: PromotionStatus,
    pub gates: Vec<GateResult>,
    pub rationale: String,
}

impl PromotionGate {
    fn validate(&self) -> Result<(), SchemaError> {
        non_empty("promotion.rationale", &self.rationale)?;
        if self.gates.is_empty() {
            return Err(SchemaError::Missing {
                field: "promotion.gates",
            });
        }
        let mut gate_names = BTreeSet::new();
        for gate in &self.gates {
            gate.validate()?;
            if !gate_names.insert(gate.name.as_str()) {
                return Err(SchemaError::Inconsistent {
                    field: "promotion.gates.name",
                });
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PromotionStatus {
    SandboxOnly,
    Candidate,
    Approved,
    Rejected,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct GateResult {
    pub name: String,
    pub status: GateStatus,
    pub evidence: String,
    #[serde(default)]
    pub waiver: Option<String>,
}

impl GateResult {
    fn validate(&self) -> Result<(), SchemaError> {
        non_empty("gate.name", &self.name)?;
        non_empty("gate.evidence", &self.evidence)?;
        if self.status == GateStatus::Waived && self.waiver.is_none() {
            return Err(SchemaError::Missing {
                field: "gate.waiver",
            });
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum GateStatus {
    Passed,
    Failed,
    Waived,
    Pending,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct RollbackMetadata {
    pub baseline_config_id: String,
    pub rollback_command: String,
    pub reason: String,
    #[serde(default)]
    pub previous_packet_id: Option<String>,
}

impl RollbackMetadata {
    fn validate(&self) -> Result<(), SchemaError> {
        non_empty("rollback.baseline_config_id", &self.baseline_config_id)?;
        non_empty("rollback.rollback_command", &self.rollback_command)?;
        non_empty("rollback.reason", &self.reason)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CostEnvelope {
    pub measured_cost_usd: f64,
    pub max_cost_usd: f64,
    pub measured_wall_sec: f64,
    pub max_wall_sec: f64,
}

impl CostEnvelope {
    fn validate(&self) -> Result<(), SchemaError> {
        expect_range(
            "cost.measured_cost_usd",
            self.measured_cost_usd,
            0.0,
            f64::MAX,
        )?;
        expect_range("cost.max_cost_usd", self.max_cost_usd, 0.0, f64::MAX)?;
        expect_range(
            "cost.measured_wall_sec",
            self.measured_wall_sec,
            0.0,
            f64::MAX,
        )?;
        expect_range("cost.max_wall_sec", self.max_wall_sec, 0.0, f64::MAX)?;
        if self.measured_cost_usd > self.max_cost_usd || self.measured_wall_sec > self.max_wall_sec
        {
            return Err(SchemaError::Inconsistent {
                field: "cost.envelope",
            });
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReviewerHarnessMetadata {
    pub harness_id: String,
    pub kind: String,
    pub provider_name: String,
    pub command: String,
    #[serde(default)]
    pub version: Option<String>,
    pub execution_mode: String,
}

impl ReviewerHarnessMetadata {
    fn validate(&self) -> Result<(), SchemaError> {
        non_empty("harness.harness_id", &self.harness_id)?;
        non_empty("harness.kind", &self.kind)?;
        non_empty("harness.provider_name", &self.provider_name)?;
        non_empty("harness.command", &self.command)?;
        non_empty("harness.execution_mode", &self.execution_mode)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReviewerModelMetadata {
    pub reviewer_id: String,
    pub harness_id: String,
    pub provider: String,
    pub model: String,
    pub prompt_hash: String,
    #[serde(default)]
    pub context_length: Option<u64>,
}

impl ReviewerModelMetadata {
    fn validate(&self) -> Result<(), SchemaError> {
        non_empty("model.reviewer_id", &self.reviewer_id)?;
        non_empty("model.harness_id", &self.harness_id)?;
        non_empty("model.provider", &self.provider)?;
        non_empty("model.model", &self.model)?;
        non_empty("model.prompt_hash", &self.prompt_hash)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ReviewerConfigImportReport {
    pub schema_version: String,
    pub packet_id: String,
    pub generated_at: String,
    pub dry_run: bool,
    pub baseline_config_id: String,
    pub candidate_config_id: String,
    pub config_digest: String,
    pub promotion_status: PromotionStatus,
    pub accepted_for_dry_run: bool,
    pub accepted_for_import: bool,
    #[serde(default)]
    pub rejection_reasons: Vec<String>,
    pub comparison: ReviewerConfigComparison,
    pub rollback: RollbackMetadata,
}

impl ReviewerConfigImportReport {
    pub fn validate(&self) -> Result<(), SchemaError> {
        expect_version(
            "schema_version",
            &self.schema_version,
            REVIEWER_CONFIG_IMPORT_REPORT_VERSION,
        )?;
        non_empty("packet_id", &self.packet_id)?;
        non_empty("generated_at", &self.generated_at)?;
        non_empty("baseline_config_id", &self.baseline_config_id)?;
        non_empty("candidate_config_id", &self.candidate_config_id)?;
        non_empty("config_digest", &self.config_digest)?;
        if self.accepted_for_import && !self.accepted_for_dry_run {
            return Err(SchemaError::Inconsistent {
                field: "accepted_for_import",
            });
        }
        if self.dry_run && self.accepted_for_import {
            return Err(SchemaError::Inconsistent {
                field: "accepted_for_import",
            });
        }
        if !self.accepted_for_import && self.rejection_reasons.is_empty() {
            return Err(SchemaError::Missing {
                field: "rejection_reasons",
            });
        }
        self.comparison.validate()?;
        self.rollback.validate()
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReviewerConfigComparison {
    pub fixture_request_id: String,
    pub baseline_verdict: Verdict,
    pub candidate_verdict: Verdict,
    pub baseline_findings: u64,
    pub candidate_findings: u64,
    pub baseline_degraded: bool,
    pub candidate_degraded: bool,
    pub reviewer_count_delta: i64,
    #[serde(default)]
    pub reviewer_deltas: Vec<ReviewerDelta>,
    pub artifact_delta_summary: String,
}

impl ReviewerConfigComparison {
    fn validate(&self) -> Result<(), SchemaError> {
        non_empty("comparison.fixture_request_id", &self.fixture_request_id)?;
        non_empty(
            "comparison.artifact_delta_summary",
            &self.artifact_delta_summary,
        )?;
        let mut reviewer_ids = BTreeSet::new();
        for delta in &self.reviewer_deltas {
            delta.validate()?;
            if !reviewer_ids.insert(delta.reviewer_id.as_str()) {
                return Err(SchemaError::Inconsistent {
                    field: "comparison.reviewer_deltas.reviewer_id",
                });
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReviewerDelta {
    pub reviewer_id: String,
    #[serde(default)]
    pub baseline_model: Option<String>,
    #[serde(default)]
    pub candidate_model: Option<String>,
    #[serde(default)]
    pub changed_fields: Vec<String>,
}

impl ReviewerDelta {
    fn validate(&self) -> Result<(), SchemaError> {
        non_empty("reviewer_delta.reviewer_id", &self.reviewer_id)?;
        if self.baseline_model.is_none() && self.candidate_model.is_none() {
            return Err(SchemaError::Missing {
                field: "reviewer_delta.model",
            });
        }
        if self.changed_fields.is_empty() {
            return Err(SchemaError::Missing {
                field: "reviewer_delta.changed_fields",
            });
        }
        Ok(())
    }
}

fn non_empty(field: &'static str, value: &str) -> Result<(), SchemaError> {
    if value.trim().is_empty() {
        Err(SchemaError::Empty { field })
    } else {
        Ok(())
    }
}

fn expect_version(
    field: &'static str,
    actual: &str,
    expected: &'static str,
) -> Result<(), SchemaError> {
    if actual == expected {
        Ok(())
    } else {
        Err(SchemaError::Version {
            field,
            actual: actual.to_string(),
            expected,
        })
    }
}

fn expect_range(field: &'static str, actual: f64, min: f64, max: f64) -> Result<(), SchemaError> {
    if actual.is_finite() && actual >= min && actual <= max {
        Ok(())
    } else {
        Err(SchemaError::OutOfRange {
            field,
            min,
            max,
            actual,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{FakeReviewerBehavior, ReviewerConfig, REVIEW_CONFIG_VERSION};

    #[test]
    fn reviewer_config_packet_requires_signature_unless_sandbox_only() {
        let mut packet = packet();
        packet.producer.sandbox_only = false;
        packet.producer.signature = None;

        assert!(matches!(
            packet.validate(),
            Err(SchemaError::Missing {
                field: "producer.signature"
            })
        ));
    }

    #[test]
    fn reviewer_config_packet_requires_model_metadata_for_every_config_reviewer() {
        let mut packet = packet();
        packet.config.reviewers.push(ReviewerConfig {
            id: "security".to_string(),
            perspective: "security".to_string(),
            model: "openrouter:openai/gpt-5-mini".to_string(),
            fake_behavior: FakeReviewerBehavior::Pass,
        });
        packet
            .prompt_hashes
            .insert("security".to_string(), "sha256:security-prompt".to_string());

        assert!(matches!(
            packet.validate(),
            Err(SchemaError::Inconsistent {
                field: "models.reviewer_id"
            })
        ));
    }

    #[test]
    fn reviewer_config_packet_rejects_duplicate_embedded_reviewer_ids() {
        let mut packet = packet();
        packet.config.reviewers.push(ReviewerConfig {
            id: "correctness".to_string(),
            perspective: "security".to_string(),
            model: "openrouter:openai/gpt-5-mini".to_string(),
            fake_behavior: FakeReviewerBehavior::Pass,
        });

        assert!(matches!(
            packet.validate(),
            Err(SchemaError::Inconsistent {
                field: "reviewers.id"
            })
        ));
    }

    #[test]
    fn reviewer_config_import_report_rejects_dry_run_import_acceptance() {
        let mut report = ReviewerConfigImportReport {
            schema_version: REVIEWER_CONFIG_IMPORT_REPORT_VERSION.to_string(),
            packet_id: "packet".to_string(),
            generated_at: "2026-06-18T00:00:00Z".to_string(),
            dry_run: true,
            baseline_config_id: "baseline".to_string(),
            candidate_config_id: "candidate".to_string(),
            config_digest: "digest".to_string(),
            promotion_status: PromotionStatus::Approved,
            accepted_for_dry_run: true,
            accepted_for_import: true,
            rejection_reasons: vec![],
            comparison: ReviewerConfigComparison {
                fixture_request_id: "fixture".to_string(),
                baseline_verdict: Verdict::Pass,
                candidate_verdict: Verdict::Pass,
                baseline_findings: 0,
                candidate_findings: 0,
                baseline_degraded: false,
                candidate_degraded: false,
                reviewer_count_delta: 0,
                reviewer_deltas: vec![],
                artifact_delta_summary: "no delta".to_string(),
            },
            rollback: RollbackMetadata {
                baseline_config_id: "baseline".to_string(),
                rollback_command: "restore".to_string(),
                reason: "test".to_string(),
                previous_packet_id: None,
            },
        };

        assert!(matches!(
            report.validate(),
            Err(SchemaError::Inconsistent {
                field: "accepted_for_import"
            })
        ));
        report.dry_run = false;
        report
            .validate()
            .expect("non-dry-run report can accept import");
    }

    #[test]
    fn reviewer_config_packet_rejects_unknown_model_harness() {
        let mut packet = packet();
        packet.models[0].harness_id = "missing-harness".to_string();

        assert!(matches!(
            packet.validate(),
            Err(SchemaError::Mismatch {
                field: "models.harness_id",
                ..
            })
        ));
    }

    #[test]
    fn reviewer_config_packet_rejects_model_metadata_mismatch() {
        let mut packet = packet();
        packet.models[0].provider = "anthropic".to_string();
        packet.models[0].model = "claude-sonnet-4-5".to_string();

        assert!(matches!(
            packet.validate(),
            Err(SchemaError::Mismatch {
                field: "models.model",
                ..
            })
        ));
    }

    #[test]
    fn reviewer_config_packet_rejects_prompt_hash_mismatch() {
        let mut packet = packet();
        packet.models[0].prompt_hash = "sha256:other-prompt".to_string();

        assert!(matches!(
            packet.validate(),
            Err(SchemaError::Mismatch {
                field: "models.prompt_hash",
                ..
            })
        ));
    }

    fn packet() -> ReviewerConfigPacket {
        ReviewerConfigPacket {
            schema_version: REVIEWER_CONFIG_PACKET_VERSION.to_string(),
            packet_id: "packet".to_string(),
            producer: ReviewerConfigProducer {
                system: "daedalus".to_string(),
                delivery_id: "delivery".to_string(),
                generated_at: "2026-06-18T00:00:00Z".to_string(),
                sandbox_only: true,
                signature: None,
            },
            benchmark: ReviewerConfigBenchmark {
                benchmark_id: "pr-review".to_string(),
                suite_id: "suite".to_string(),
                arena_version: "0.2.0".to_string(),
                run_id: "run".to_string(),
                task_count: 1,
                score_distribution: ScoreDistribution {
                    min: 0.5,
                    mean: 0.6,
                    median: 0.6,
                    max: 0.7,
                    certified_trials: 5,
                },
            },
            promotion: PromotionGate {
                status: PromotionStatus::SandboxOnly,
                gates: vec![GateResult {
                    name: "G3".to_string(),
                    status: GateStatus::Pending,
                    evidence: "approval pending".to_string(),
                    waiver: None,
                }],
                rationale: "sandbox dry run".to_string(),
            },
            rollback: RollbackMetadata {
                baseline_config_id: "baseline".to_string(),
                rollback_command: "restore baseline".to_string(),
                reason: "sandbox".to_string(),
                previous_packet_id: None,
            },
            cost: CostEnvelope {
                measured_cost_usd: 0.1,
                max_cost_usd: 1.0,
                measured_wall_sec: 10.0,
                max_wall_sec: 100.0,
            },
            harnesses: vec![ReviewerHarnessMetadata {
                harness_id: "pi-openrouter".to_string(),
                kind: "pi".to_string(),
                provider_name: "openrouter".to_string(),
                command: "pi".to_string(),
                version: Some("0.78.1".to_string()),
                execution_mode: "sandbox".to_string(),
            }],
            models: vec![ReviewerModelMetadata {
                reviewer_id: "correctness".to_string(),
                harness_id: "pi-openrouter".to_string(),
                provider: "openrouter".to_string(),
                model: "openai/gpt-5-mini".to_string(),
                prompt_hash: "sha256:prompt".to_string(),
                context_length: Some(128_000),
            }],
            prompt_hashes: BTreeMap::from([(
                "correctness".to_string(),
                "sha256:prompt".to_string(),
            )]),
            config_hash: "sha256:config".to_string(),
            config: ReviewConfig {
                schema_version: REVIEW_CONFIG_VERSION.to_string(),
                config_id: "candidate".to_string(),
                reviewers: vec![ReviewerConfig {
                    id: "correctness".to_string(),
                    perspective: "correctness".to_string(),
                    model: "openrouter:openai/gpt-5-mini".to_string(),
                    fake_behavior: FakeReviewerBehavior::Pass,
                }],
                confidence_min: 0.7,
            },
        }
    }
}
