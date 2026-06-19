use crate::{Finding, ReviewRequest, ReviewerArtifact, SchemaError, Severity};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

pub const EVAL_TASK_SUITE_VERSION: &str = "eval-task-suite.v1";
pub const HARNESS_PROFILE_VERSION: &str = "harness-profile.v1";
pub const MODEL_CANDIDATE_VERSION: &str = "model-candidate.v1";
pub const HARNESS_MODEL_MATRIX_VERSION: &str = "harness-model-matrix.v1";
pub const HARNESS_MODEL_EVALUATION_REPORT_VERSION: &str = "harness-model-evaluation-report.v1";
pub const EVAL_READINESS_REPORT_VERSION: &str = "eval-readiness-report.v1";
pub const EVAL_BUDGET_ESTIMATE_REPORT_VERSION: &str = "eval-budget-estimate-report.v1";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct EvalTaskSuite {
    pub schema_version: String,
    pub suite_id: String,
    #[serde(default)]
    pub description: Option<String>,
    pub tasks: Vec<EvalTask>,
}

impl EvalTaskSuite {
    pub fn validate(&self) -> Result<(), SchemaError> {
        expect_version(
            "schema_version",
            &self.schema_version,
            EVAL_TASK_SUITE_VERSION,
        )?;
        non_empty("suite_id", &self.suite_id)?;
        if self.tasks.is_empty() {
            return Err(SchemaError::Missing { field: "tasks" });
        }
        let mut task_ids = BTreeSet::new();
        for task in &self.tasks {
            task.validate()?;
            if !task_ids.insert(task.task_id.as_str()) {
                return Err(SchemaError::Inconsistent {
                    field: "tasks.task_id",
                });
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct EvalTask {
    pub task_id: String,
    pub review_request: ReviewRequest,
    #[serde(default)]
    pub expected_findings: Vec<ExpectedFinding>,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub expected_degraded: bool,
    #[serde(default = "default_min_score")]
    pub min_score: f64,
    #[serde(default)]
    pub max_false_positives: u64,
}

impl EvalTask {
    pub fn validate(&self) -> Result<(), SchemaError> {
        non_empty("task_id", &self.task_id)?;
        self.review_request.validate()?;
        expect_range("task.min_score", self.min_score, 0.0, 1.0)?;
        for finding in &self.expected_findings {
            finding.validate()?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ExpectedFinding {
    pub category: String,
    pub severity: Severity,
    pub path: String,
    #[serde(default)]
    pub line: Option<u64>,
    pub evidence: String,
}

impl ExpectedFinding {
    pub fn validate(&self) -> Result<(), SchemaError> {
        non_empty("expected_finding.category", &self.category)?;
        non_empty("expected_finding.path", &self.path)?;
        non_empty("expected_finding.evidence", &self.evidence)
    }

    pub fn matches(&self, finding: &Finding) -> bool {
        self.category == finding.category
            && self.severity == finding.severity
            && self.path == finding.citation.path
            && self.line == finding.citation.line
            && self.evidence == finding.evidence
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct HarnessModelMatrix {
    pub schema_version: String,
    pub matrix_id: String,
    pub observed_at: String,
    pub harnesses: Vec<HarnessProfile>,
    pub models: Vec<ModelCandidate>,
    #[serde(default)]
    pub stale_model_patterns: Vec<String>,
    #[serde(default)]
    pub drift_scan_paths: Vec<String>,
}

impl HarnessModelMatrix {
    pub fn validate(&self) -> Result<(), SchemaError> {
        expect_version(
            "schema_version",
            &self.schema_version,
            HARNESS_MODEL_MATRIX_VERSION,
        )?;
        non_empty("matrix_id", &self.matrix_id)?;
        non_empty("observed_at", &self.observed_at)?;
        if self.harnesses.is_empty() {
            return Err(SchemaError::Missing { field: "harnesses" });
        }
        if self.models.is_empty() {
            return Err(SchemaError::Missing { field: "models" });
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
        let mut model_ids = BTreeSet::new();
        for model in &self.models {
            model.validate()?;
            if !model_ids.insert(model.model_id.as_str()) {
                return Err(SchemaError::Inconsistent {
                    field: "models.model_id",
                });
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct HarnessProfile {
    pub schema_version: String,
    pub harness_id: String,
    pub command: String,
    #[serde(default)]
    pub version: Option<String>,
    #[serde(default)]
    pub path: Option<String>,
    #[serde(default)]
    pub notes: Option<String>,
}

impl HarnessProfile {
    pub fn validate(&self) -> Result<(), SchemaError> {
        expect_version(
            "schema_version",
            &self.schema_version,
            HARNESS_PROFILE_VERSION,
        )?;
        non_empty("harness_id", &self.harness_id)?;
        non_empty("command", &self.command)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ModelCandidate {
    pub schema_version: String,
    pub model_id: String,
    pub provider: String,
    pub context_length: u64,
    pub max_completion_tokens: u64,
    pub input_usd_per_m: f64,
    pub output_usd_per_m: f64,
    #[serde(default)]
    pub cache_read_usd_per_m: Option<f64>,
    #[serde(default)]
    pub supported_parameters: Vec<String>,
    pub catalog_source: String,
    pub catalog_observed_at: String,
    #[serde(default)]
    pub previous: Option<ModelCatalogSnapshot>,
}

impl ModelCandidate {
    pub fn validate(&self) -> Result<(), SchemaError> {
        expect_version(
            "schema_version",
            &self.schema_version,
            MODEL_CANDIDATE_VERSION,
        )?;
        non_empty("model_id", &self.model_id)?;
        non_empty("provider", &self.provider)?;
        non_empty("catalog_source", &self.catalog_source)?;
        non_empty("catalog_observed_at", &self.catalog_observed_at)?;
        expect_range("model.input_usd_per_m", self.input_usd_per_m, 0.0, f64::MAX)?;
        expect_range(
            "model.output_usd_per_m",
            self.output_usd_per_m,
            0.0,
            f64::MAX,
        )?;
        if let Some(cache_read) = self.cache_read_usd_per_m {
            expect_range("model.cache_read_usd_per_m", cache_read, 0.0, f64::MAX)?;
        }
        if let Some(previous) = &self.previous {
            previous.validate()?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ModelCatalogSnapshot {
    pub observed_at: String,
    pub context_length: u64,
    pub max_completion_tokens: u64,
    pub input_usd_per_m: f64,
    pub output_usd_per_m: f64,
    #[serde(default)]
    pub cache_read_usd_per_m: Option<f64>,
}

impl ModelCatalogSnapshot {
    pub fn validate(&self) -> Result<(), SchemaError> {
        non_empty("model.previous.observed_at", &self.observed_at)?;
        expect_range(
            "model.previous.input_usd_per_m",
            self.input_usd_per_m,
            0.0,
            f64::MAX,
        )?;
        expect_range(
            "model.previous.output_usd_per_m",
            self.output_usd_per_m,
            0.0,
            f64::MAX,
        )
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct HarnessModelEvaluationReport {
    pub schema_version: String,
    pub report_id: String,
    pub generated_at: String,
    pub suite_id: String,
    pub matrix_id: String,
    pub summary: HarnessModelEvaluationSummary,
    pub cells: Vec<HarnessModelEvaluationCell>,
    #[serde(default)]
    pub stale_model_findings: Vec<StaleModelFinding>,
    #[serde(default)]
    pub catalog_deltas: Vec<ModelCatalogDelta>,
}

impl HarnessModelEvaluationReport {
    pub fn validate(&self) -> Result<(), SchemaError> {
        expect_version(
            "schema_version",
            &self.schema_version,
            HARNESS_MODEL_EVALUATION_REPORT_VERSION,
        )?;
        non_empty("report_id", &self.report_id)?;
        non_empty("generated_at", &self.generated_at)?;
        non_empty("suite_id", &self.suite_id)?;
        non_empty("matrix_id", &self.matrix_id)?;
        if self.cells.is_empty() {
            return Err(SchemaError::Missing { field: "cells" });
        }
        let mut cell_ids = BTreeSet::new();
        let mut transcript_paths = BTreeSet::new();
        for cell in &self.cells {
            cell.validate()?;
            if !cell_ids.insert(cell.cell_id.as_str()) {
                return Err(SchemaError::Inconsistent {
                    field: "cells.cell_id",
                });
            }
            if !transcript_paths.insert(cell.transcript_path.as_str()) {
                return Err(SchemaError::Inconsistent {
                    field: "cells.transcript_path",
                });
            }
        }
        for finding in &self.stale_model_findings {
            finding.validate()?;
        }
        for delta in &self.catalog_deltas {
            delta.validate()?;
        }
        self.summary.validate_for_cells(&self.cells)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct EvalReadinessReport {
    pub schema_version: String,
    pub report_id: String,
    pub generated_at: String,
    pub suite_id: String,
    pub matrix_id: String,
    #[serde(default)]
    pub peer_profiles_observed_at: Option<String>,
    pub summary: EvalReadinessSummary,
    pub cells: Vec<EvalReadinessCell>,
}

impl EvalReadinessReport {
    pub fn validate(&self) -> Result<(), SchemaError> {
        expect_version(
            "schema_version",
            &self.schema_version,
            EVAL_READINESS_REPORT_VERSION,
        )?;
        non_empty("report_id", &self.report_id)?;
        non_empty("generated_at", &self.generated_at)?;
        non_empty("suite_id", &self.suite_id)?;
        non_empty("matrix_id", &self.matrix_id)?;
        if let Some(observed_at) = &self.peer_profiles_observed_at {
            non_empty("peer_profiles_observed_at", observed_at)?;
        }
        if self.cells.is_empty() {
            return Err(SchemaError::Missing { field: "cells" });
        }
        let mut cell_ids = BTreeSet::new();
        for cell in &self.cells {
            cell.validate()?;
            if !cell_ids.insert(cell.cell_id.as_str()) {
                return Err(SchemaError::Inconsistent {
                    field: "cells.cell_id",
                });
            }
        }
        self.summary.validate_for_cells(&self.cells)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct EvalReadinessSummary {
    pub total_cells: u64,
    pub runnable_cells: u64,
    pub unavailable_harness_cells: u64,
    pub unavailable_peer_runner_cells: u64,
    pub missing_profile_cells: u64,
    pub missing_env_cells: u64,
    pub budget_blocked_cells: u64,
}

impl EvalReadinessSummary {
    fn validate_for_cells(&self, cells: &[EvalReadinessCell]) -> Result<(), SchemaError> {
        let total_cells = cells.len() as u64;
        let runnable_cells = cells.iter().filter(|cell| cell.runnable).count() as u64;
        let unavailable_harness_cells =
            cells.iter().filter(|cell| !cell.harness_available).count() as u64;
        let unavailable_peer_runner_cells = cells
            .iter()
            .filter(|cell| cell.peer_profile_found && !cell.peer_runner_available)
            .count() as u64;
        let missing_profile_cells =
            cells.iter().filter(|cell| !cell.peer_profile_found).count() as u64;
        let missing_env_cells = cells
            .iter()
            .filter(|cell| !cell.env_missing.is_empty())
            .count() as u64;
        let budget_blocked_cells = cells
            .iter()
            .filter(|cell| cell.requires_provider_budget_ack && !cell.provider_budget_acknowledged)
            .count() as u64;

        if self.total_cells != total_cells {
            return Err(SchemaError::Inconsistent {
                field: "readiness_summary.total_cells",
            });
        }
        if self.runnable_cells != runnable_cells {
            return Err(SchemaError::Inconsistent {
                field: "readiness_summary.runnable_cells",
            });
        }
        if self.unavailable_harness_cells != unavailable_harness_cells {
            return Err(SchemaError::Inconsistent {
                field: "readiness_summary.unavailable_harness_cells",
            });
        }
        if self.unavailable_peer_runner_cells != unavailable_peer_runner_cells {
            return Err(SchemaError::Inconsistent {
                field: "readiness_summary.unavailable_peer_runner_cells",
            });
        }
        if self.missing_profile_cells != missing_profile_cells {
            return Err(SchemaError::Inconsistent {
                field: "readiness_summary.missing_profile_cells",
            });
        }
        if self.missing_env_cells != missing_env_cells {
            return Err(SchemaError::Inconsistent {
                field: "readiness_summary.missing_env_cells",
            });
        }
        if self.budget_blocked_cells != budget_blocked_cells {
            return Err(SchemaError::Inconsistent {
                field: "readiness_summary.budget_blocked_cells",
            });
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct EvalReadinessCell {
    pub cell_id: String,
    pub harness_id: String,
    pub model_id: String,
    pub task_id: String,
    pub harness_available: bool,
    #[serde(default)]
    pub harness_version: Option<String>,
    #[serde(default)]
    pub harness_path: Option<String>,
    pub peer_profile_found: bool,
    pub peer_runner_available: bool,
    #[serde(default)]
    pub peer_runner_path: Option<String>,
    #[serde(default)]
    pub env_required: Vec<String>,
    #[serde(default)]
    pub env_missing: Vec<String>,
    pub requires_provider_budget_ack: bool,
    pub provider_budget_acknowledged: bool,
    pub runnable: bool,
    #[serde(default)]
    pub blockers: Vec<String>,
}

impl EvalReadinessCell {
    pub fn validate(&self) -> Result<(), SchemaError> {
        non_empty("readiness_cell.cell_id", &self.cell_id)?;
        non_empty("readiness_cell.harness_id", &self.harness_id)?;
        non_empty("readiness_cell.model_id", &self.model_id)?;
        non_empty("readiness_cell.task_id", &self.task_id)?;
        if let Some(version) = &self.harness_version {
            non_empty("readiness_cell.harness_version", version)?;
        }
        if let Some(path) = &self.harness_path {
            non_empty("readiness_cell.harness_path", path)?;
        }
        if let Some(path) = &self.peer_runner_path {
            non_empty("readiness_cell.peer_runner_path", path)?;
        }
        validate_unique_non_empty("readiness_cell.env_required", &self.env_required)?;
        validate_unique_non_empty("readiness_cell.env_missing", &self.env_missing)?;
        validate_unique_non_empty("readiness_cell.blockers", &self.blockers)?;
        let required = self.env_required.iter().collect::<BTreeSet<_>>();
        for missing in &self.env_missing {
            if !required.contains(missing) {
                return Err(SchemaError::Inconsistent {
                    field: "readiness_cell.env_missing",
                });
            }
        }
        let budget_blocked =
            self.requires_provider_budget_ack && !self.provider_budget_acknowledged;
        if self.runnable {
            if !self.harness_available
                || !self.peer_profile_found
                || !self.peer_runner_available
                || !self.env_missing.is_empty()
                || budget_blocked
                || !self.blockers.is_empty()
            {
                return Err(SchemaError::Inconsistent {
                    field: "readiness_cell.runnable",
                });
            }
        } else if self.blockers.is_empty() {
            return Err(SchemaError::Missing {
                field: "readiness_cell.blockers",
            });
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct EvalBudgetEstimateReport {
    pub schema_version: String,
    pub report_id: String,
    pub generated_at: String,
    pub suite_id: String,
    pub matrix_id: String,
    pub readiness_report_id: String,
    pub prompt_tokens_per_cell: u64,
    pub completion_tokens_per_cell: u64,
    pub retry_count: u64,
    pub summary: EvalBudgetEstimateSummary,
    pub cells: Vec<EvalBudgetEstimateCell>,
}

impl EvalBudgetEstimateReport {
    pub fn validate(&self) -> Result<(), SchemaError> {
        expect_version(
            "schema_version",
            &self.schema_version,
            EVAL_BUDGET_ESTIMATE_REPORT_VERSION,
        )?;
        non_empty("report_id", &self.report_id)?;
        non_empty("generated_at", &self.generated_at)?;
        non_empty("suite_id", &self.suite_id)?;
        non_empty("matrix_id", &self.matrix_id)?;
        non_empty("readiness_report_id", &self.readiness_report_id)?;
        expect_positive_u64("prompt_tokens_per_cell", self.prompt_tokens_per_cell)?;
        expect_positive_u64(
            "completion_tokens_per_cell",
            self.completion_tokens_per_cell,
        )?;
        expect_positive_u64("retry_count", self.retry_count)?;
        if self.cells.is_empty() {
            return Err(SchemaError::Missing { field: "cells" });
        }

        let mut cell_ids = BTreeSet::new();
        for cell in &self.cells {
            cell.validate()?;
            if !cell_ids.insert(cell.cell_id.as_str()) {
                return Err(SchemaError::Inconsistent {
                    field: "budget_cells.cell_id",
                });
            }
            if cell.prompt_tokens != self.prompt_tokens_per_cell {
                return Err(SchemaError::Inconsistent {
                    field: "budget_cell.prompt_tokens",
                });
            }
            if cell.completion_tokens != self.completion_tokens_per_cell {
                return Err(SchemaError::Inconsistent {
                    field: "budget_cell.completion_tokens",
                });
            }
            if cell.retry_count != self.retry_count {
                return Err(SchemaError::Inconsistent {
                    field: "budget_cell.retry_count",
                });
            }
        }
        self.summary.validate_for_cells(&self.cells)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct EvalBudgetEstimateSummary {
    pub total_cells: u64,
    pub estimateable_cells: u64,
    pub blocked_cells: u64,
    pub estimated_total_cost_usd: f64,
    pub max_single_cell_cost_usd: f64,
}

impl EvalBudgetEstimateSummary {
    fn validate_for_cells(&self, cells: &[EvalBudgetEstimateCell]) -> Result<(), SchemaError> {
        let total_cells = cells.len() as u64;
        let estimateable_cells = cells.iter().filter(|cell| cell.estimateable).count() as u64;
        let blocked_cells = cells.iter().filter(|cell| !cell.estimateable).count() as u64;
        let estimated_total_cost_usd = cells.iter().map(|cell| cell.estimated_cost_usd).sum();
        let max_single_cell_cost_usd = cells
            .iter()
            .map(|cell| cell.estimated_cost_usd)
            .fold(0.0, f64::max);

        if self.total_cells != total_cells {
            return Err(SchemaError::Inconsistent {
                field: "budget_summary.total_cells",
            });
        }
        if self.estimateable_cells != estimateable_cells {
            return Err(SchemaError::Inconsistent {
                field: "budget_summary.estimateable_cells",
            });
        }
        if self.blocked_cells != blocked_cells {
            return Err(SchemaError::Inconsistent {
                field: "budget_summary.blocked_cells",
            });
        }
        if !float_close(self.estimated_total_cost_usd, estimated_total_cost_usd) {
            return Err(SchemaError::Inconsistent {
                field: "budget_summary.estimated_total_cost_usd",
            });
        }
        if !float_close(self.max_single_cell_cost_usd, max_single_cell_cost_usd) {
            return Err(SchemaError::Inconsistent {
                field: "budget_summary.max_single_cell_cost_usd",
            });
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct EvalBudgetEstimateCell {
    pub cell_id: String,
    pub harness_id: String,
    pub model_id: String,
    pub task_id: String,
    pub readiness_runnable: bool,
    pub readiness_harness_available: bool,
    pub readiness_peer_profile_found: bool,
    pub readiness_peer_runner_available: bool,
    #[serde(default)]
    pub readiness_env_missing: Vec<String>,
    pub budget_ack_required: bool,
    pub budget_acknowledged: bool,
    pub estimateable: bool,
    pub prompt_tokens: u64,
    pub completion_tokens: u64,
    pub retry_count: u64,
    pub estimated_cost_usd: f64,
    #[serde(default)]
    pub blockers: Vec<String>,
}

impl EvalBudgetEstimateCell {
    pub fn validate(&self) -> Result<(), SchemaError> {
        non_empty("budget_cell.cell_id", &self.cell_id)?;
        non_empty("budget_cell.harness_id", &self.harness_id)?;
        non_empty("budget_cell.model_id", &self.model_id)?;
        non_empty("budget_cell.task_id", &self.task_id)?;
        validate_unique_non_empty(
            "budget_cell.readiness_env_missing",
            &self.readiness_env_missing,
        )?;
        expect_positive_u64("budget_cell.prompt_tokens", self.prompt_tokens)?;
        expect_positive_u64("budget_cell.completion_tokens", self.completion_tokens)?;
        expect_positive_u64("budget_cell.retry_count", self.retry_count)?;
        expect_range(
            "budget_cell.estimated_cost_usd",
            self.estimated_cost_usd,
            0.0,
            f64::MAX,
        )?;
        validate_unique_non_empty("budget_cell.blockers", &self.blockers)?;
        let should_be_estimateable = self.should_be_estimateable()?;
        if self.estimateable != should_be_estimateable {
            return Err(SchemaError::Inconsistent {
                field: "budget_cell.estimateable",
            });
        }
        if self.estimateable {
            if self.estimated_cost_usd <= 0.0 {
                return Err(SchemaError::Inconsistent {
                    field: "budget_cell.estimated_cost_usd",
                });
            }
        } else {
            if self.blockers.is_empty() {
                return Err(SchemaError::Missing {
                    field: "budget_cell.blockers",
                });
            }
            if self.estimated_cost_usd != 0.0 {
                return Err(SchemaError::Inconsistent {
                    field: "budget_cell.estimated_cost_usd",
                });
            }
        }
        Ok(())
    }

    fn should_be_estimateable(&self) -> Result<bool, SchemaError> {
        if self.readiness_runnable {
            if !self.readiness_harness_available
                || !self.readiness_peer_profile_found
                || !self.readiness_peer_runner_available
                || !self.readiness_env_missing.is_empty()
                || (self.budget_ack_required && !self.budget_acknowledged)
                || !self.blockers.is_empty()
            {
                return Err(SchemaError::Inconsistent {
                    field: "budget_cell.readiness_runnable",
                });
            }
            return Ok(true);
        }

        let budget_only_blocked = self.budget_ack_required
            && !self.budget_acknowledged
            && self.readiness_harness_available
            && self.readiness_peer_profile_found
            && self.readiness_peer_runner_available
            && self.readiness_env_missing.is_empty()
            && self.blockers.len() == 1;
        Ok(budget_only_blocked)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct HarnessModelEvaluationSummary {
    pub total_cells: u64,
    pub valid_artifacts: u64,
    pub warn_cells: u64,
    pub unavailable_cells: u64,
    pub degraded_cells: u64,
    pub failed_cells: u64,
    pub average_score: f64,
}

impl HarnessModelEvaluationSummary {
    fn validate_for_cells(&self, cells: &[HarnessModelEvaluationCell]) -> Result<(), SchemaError> {
        let total_cells = cells.len() as u64;
        let valid_artifacts = cells.iter().filter(|cell| cell.artifact_valid).count() as u64;
        let warn_cells = cells
            .iter()
            .filter(|cell| cell.status == EvalCellStatus::Warn)
            .count() as u64;
        let unavailable_cells = cells
            .iter()
            .filter(|cell| cell.status == EvalCellStatus::Unavailable)
            .count() as u64;
        let degraded_cells = cells.iter().filter(|cell| cell.degraded).count() as u64;
        let failed_cells = cells
            .iter()
            .filter(|cell| cell.status == EvalCellStatus::Fail)
            .count() as u64;
        if self.total_cells != total_cells {
            return Err(SchemaError::Inconsistent {
                field: "summary.total_cells",
            });
        }
        if self.valid_artifacts != valid_artifacts {
            return Err(SchemaError::Inconsistent {
                field: "summary.valid_artifacts",
            });
        }
        if self.warn_cells != warn_cells {
            return Err(SchemaError::Inconsistent {
                field: "summary.warn_cells",
            });
        }
        if self.unavailable_cells != unavailable_cells {
            return Err(SchemaError::Inconsistent {
                field: "summary.unavailable_cells",
            });
        }
        if self.degraded_cells != degraded_cells {
            return Err(SchemaError::Inconsistent {
                field: "summary.degraded_cells",
            });
        }
        if self.failed_cells != failed_cells {
            return Err(SchemaError::Inconsistent {
                field: "summary.failed_cells",
            });
        }
        expect_range("summary.average_score", self.average_score, 0.0, 1.0)?;
        let expected_average =
            cells.iter().map(|cell| cell.score).sum::<f64>() / cells.len() as f64;
        if (self.average_score - expected_average).abs() > f64::EPSILON {
            return Err(SchemaError::Inconsistent {
                field: "summary.average_score",
            });
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct HarnessModelEvaluationCell {
    pub cell_id: String,
    pub harness_id: String,
    pub model_id: String,
    pub task_id: String,
    pub execution_mode: EvalExecutionMode,
    pub status: EvalCellStatus,
    pub artifact_valid: bool,
    #[serde(default)]
    pub reviewer_artifact: Option<ReviewerArtifact>,
    pub expected_findings_found: u64,
    pub expected_findings_total: u64,
    pub false_positives: u64,
    pub score: f64,
    pub latency_ms: u64,
    pub cost_usd: f64,
    pub degraded: bool,
    pub transcript_path: String,
    #[serde(default)]
    pub failure_reason: Option<String>,
}

impl HarnessModelEvaluationCell {
    pub fn validate(&self) -> Result<(), SchemaError> {
        non_empty("cell_id", &self.cell_id)?;
        non_empty("harness_id", &self.harness_id)?;
        non_empty("model_id", &self.model_id)?;
        non_empty("task_id", &self.task_id)?;
        non_empty("transcript_path", &self.transcript_path)?;
        expect_range("cell.score", self.score, 0.0, 1.0)?;
        expect_range("cell.cost_usd", self.cost_usd, 0.0, f64::MAX)?;
        if self.expected_findings_found > self.expected_findings_total {
            return Err(SchemaError::Inconsistent {
                field: "cell.expected_findings_found",
            });
        }
        if self.execution_mode == EvalExecutionMode::OfflineContract
            && self.status == EvalCellStatus::Pass
        {
            return Err(SchemaError::Inconsistent {
                field: "cell.status",
            });
        }
        if let Some(artifact) = &self.reviewer_artifact {
            artifact.validate()?;
            if !self.artifact_valid {
                return Err(SchemaError::Inconsistent {
                    field: "cell.artifact_valid",
                });
            }
        }
        if self.reviewer_artifact.is_none() && self.artifact_valid {
            return Err(SchemaError::Inconsistent {
                field: "cell.artifact_valid",
            });
        }
        if self.status == EvalCellStatus::Unavailable && self.failure_reason.is_none() {
            return Err(SchemaError::Missing {
                field: "cell.failure_reason",
            });
        }
        if self.status == EvalCellStatus::Degraded && self.failure_reason.is_none() {
            return Err(SchemaError::Missing {
                field: "cell.failure_reason",
            });
        }
        if self.status == EvalCellStatus::Pass
            || self.status == EvalCellStatus::Warn
            || self.status == EvalCellStatus::Degraded
        {
            if !self.artifact_valid || self.reviewer_artifact.is_none() {
                return Err(SchemaError::Inconsistent {
                    field: "cell.status",
                });
            }
        }
        if self.status == EvalCellStatus::Degraded && !self.degraded {
            return Err(SchemaError::Inconsistent {
                field: "cell.degraded",
            });
        }
        if self.degraded
            && self.status != EvalCellStatus::Degraded
            && self.status != EvalCellStatus::Fail
        {
            return Err(SchemaError::Inconsistent {
                field: "cell.degraded",
            });
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum EvalExecutionMode {
    OfflineContract,
    LiveHarness,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum EvalCellStatus {
    Pass,
    Warn,
    Fail,
    Unavailable,
    Degraded,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct StaleModelFinding {
    pub pattern: String,
    pub path: String,
    pub line: u64,
    pub text: String,
}

impl StaleModelFinding {
    pub fn validate(&self) -> Result<(), SchemaError> {
        non_empty("stale_model.pattern", &self.pattern)?;
        non_empty("stale_model.path", &self.path)?;
        non_empty("stale_model.text", &self.text)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ModelCatalogDelta {
    pub model_id: String,
    pub field: String,
    pub previous: String,
    pub current: String,
}

impl ModelCatalogDelta {
    pub fn validate(&self) -> Result<(), SchemaError> {
        non_empty("catalog_delta.model_id", &self.model_id)?;
        non_empty("catalog_delta.field", &self.field)?;
        non_empty("catalog_delta.previous", &self.previous)?;
        non_empty("catalog_delta.current", &self.current)
    }
}

fn default_min_score() -> f64 {
    1.0
}

fn non_empty(field: &'static str, value: &str) -> Result<(), SchemaError> {
    if value.trim().is_empty() {
        Err(SchemaError::Empty { field })
    } else {
        Ok(())
    }
}

fn validate_unique_non_empty(field: &'static str, values: &[String]) -> Result<(), SchemaError> {
    let mut seen = BTreeSet::new();
    for value in values {
        non_empty(field, value)?;
        if !seen.insert(value.as_str()) {
            return Err(SchemaError::Inconsistent { field });
        }
    }
    Ok(())
}

fn expect_positive_u64(field: &'static str, actual: u64) -> Result<(), SchemaError> {
    if actual == 0 {
        return Err(SchemaError::OutOfRange {
            field,
            min: 1.0,
            max: f64::MAX,
            actual: 0.0,
        });
    }
    Ok(())
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

fn float_close(left: f64, right: f64) -> bool {
    (left - right).abs() <= 0.000_000_001
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn harness_model_eval_report_rejects_average_score_drift() {
        let report = HarnessModelEvaluationReport {
            schema_version: HARNESS_MODEL_EVALUATION_REPORT_VERSION.to_string(),
            report_id: "report".to_string(),
            generated_at: "2026-06-18".to_string(),
            suite_id: "suite".to_string(),
            matrix_id: "matrix".to_string(),
            summary: HarnessModelEvaluationSummary {
                total_cells: 2,
                valid_artifacts: 0,
                warn_cells: 0,
                unavailable_cells: 2,
                degraded_cells: 0,
                failed_cells: 0,
                average_score: 0.0,
            },
            cells: vec![cell("one", 0.0), cell("two", 1.0)],
            stale_model_findings: vec![],
            catalog_deltas: vec![],
        };

        assert!(report.validate().is_err());
    }

    #[test]
    fn eval_readiness_report_rejects_runnable_cell_with_budget_blocker() {
        let mut report = readiness_report();
        report.cells[0].runnable = true;
        report.cells[0].blockers.clear();

        assert!(matches!(
            report.validate(),
            Err(SchemaError::Inconsistent {
                field: "readiness_cell.runnable"
            })
        ));
    }

    #[test]
    fn eval_readiness_report_validates_blocked_cell_summary() {
        readiness_report()
            .validate()
            .expect("blocked readiness report validates");
    }

    #[test]
    fn eval_budget_estimate_report_rejects_total_cost_drift() {
        let mut report = budget_estimate_report();
        report.summary.estimated_total_cost_usd += 0.01;

        assert!(matches!(
            report.validate(),
            Err(SchemaError::Inconsistent {
                field: "budget_summary.estimated_total_cost_usd"
            })
        ));
    }

    #[test]
    fn eval_budget_estimate_report_rejects_estimateable_infra_blocker() {
        let mut report = budget_estimate_report();
        report.cells[0].readiness_peer_runner_available = false;
        report.cells[0]
            .blockers
            .push("peer harness runner unavailable".to_string());

        assert!(matches!(
            report.validate(),
            Err(SchemaError::Inconsistent {
                field: "budget_cell.estimateable"
            })
        ));
    }

    #[test]
    fn eval_budget_estimate_report_rejects_unblocked_unrunnable_estimateable_cell() {
        let mut report = budget_estimate_report();
        report.cells[0].blockers.clear();

        assert!(matches!(
            report.validate(),
            Err(SchemaError::Inconsistent {
                field: "budget_cell.estimateable"
            })
        ));
    }

    #[test]
    fn eval_budget_estimate_report_validates_estimateable_cells() {
        budget_estimate_report()
            .validate()
            .expect("budget estimate report validates");
    }

    fn readiness_report() -> EvalReadinessReport {
        EvalReadinessReport {
            schema_version: EVAL_READINESS_REPORT_VERSION.to_string(),
            report_id: "readiness".to_string(),
            generated_at: "2026-06-19".to_string(),
            suite_id: "suite".to_string(),
            matrix_id: "matrix".to_string(),
            peer_profiles_observed_at: Some("2026-06-19".to_string()),
            summary: EvalReadinessSummary {
                total_cells: 1,
                runnable_cells: 0,
                unavailable_harness_cells: 0,
                unavailable_peer_runner_cells: 0,
                missing_profile_cells: 0,
                missing_env_cells: 1,
                budget_blocked_cells: 1,
            },
            cells: vec![EvalReadinessCell {
                cell_id: "pi__fake_model__task".to_string(),
                harness_id: "pi".to_string(),
                model_id: "fake/model".to_string(),
                task_id: "task".to_string(),
                harness_available: true,
                harness_version: Some("0.78.1".to_string()),
                harness_path: Some("/bin/pi".to_string()),
                peer_profile_found: true,
                peer_runner_available: true,
                peer_runner_path: Some("/bin/cerberus-peer-harness".to_string()),
                env_required: vec!["OPENROUTER_API_KEY".to_string()],
                env_missing: vec!["OPENROUTER_API_KEY".to_string()],
                requires_provider_budget_ack: true,
                provider_budget_acknowledged: false,
                runnable: false,
                blockers: vec![
                    "missing environment variable(s): OPENROUTER_API_KEY".to_string(),
                    "provider budget acknowledgement missing".to_string(),
                ],
            }],
        }
    }

    fn budget_estimate_report() -> EvalBudgetEstimateReport {
        EvalBudgetEstimateReport {
            schema_version: EVAL_BUDGET_ESTIMATE_REPORT_VERSION.to_string(),
            report_id: "budget".to_string(),
            generated_at: "2026-06-19".to_string(),
            suite_id: "suite".to_string(),
            matrix_id: "matrix".to_string(),
            readiness_report_id: "readiness".to_string(),
            prompt_tokens_per_cell: 10_000,
            completion_tokens_per_cell: 2_000,
            retry_count: 2,
            summary: EvalBudgetEstimateSummary {
                total_cells: 1,
                estimateable_cells: 1,
                blocked_cells: 0,
                estimated_total_cost_usd: 0.048,
                max_single_cell_cost_usd: 0.048,
            },
            cells: vec![EvalBudgetEstimateCell {
                cell_id: "pi__fake_model__task".to_string(),
                harness_id: "pi".to_string(),
                model_id: "fake/model".to_string(),
                task_id: "task".to_string(),
                readiness_runnable: false,
                readiness_harness_available: true,
                readiness_peer_profile_found: true,
                readiness_peer_runner_available: true,
                readiness_env_missing: Vec::new(),
                budget_ack_required: true,
                budget_acknowledged: false,
                estimateable: true,
                prompt_tokens: 10_000,
                completion_tokens: 2_000,
                retry_count: 2,
                estimated_cost_usd: 0.048,
                blockers: vec!["provider budget acknowledgement missing".to_string()],
            }],
        }
    }

    fn cell(cell_id: &str, score: f64) -> HarnessModelEvaluationCell {
        HarnessModelEvaluationCell {
            cell_id: cell_id.to_string(),
            harness_id: "pi".to_string(),
            model_id: "fake/model".to_string(),
            task_id: "task".to_string(),
            execution_mode: EvalExecutionMode::OfflineContract,
            status: EvalCellStatus::Unavailable,
            artifact_valid: false,
            reviewer_artifact: None,
            expected_findings_found: 0,
            expected_findings_total: 0,
            false_positives: 0,
            score,
            latency_ms: 0,
            cost_usd: 0.0,
            degraded: false,
            transcript_path: format!("transcripts/{cell_id}.txt"),
            failure_reason: Some("not installed".to_string()),
        }
    }
}
