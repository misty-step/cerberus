use crate::{review, CoreError};
use cerberus_schema::{
    EvalCellStatus, EvalExecutionMode, EvalTask, EvalTaskSuite, ExpectedFinding,
    FakeReviewerBehavior, HarnessModelEvaluationCell, HarnessModelEvaluationReport,
    HarnessModelEvaluationSummary, HarnessModelMatrix, HarnessProfile, ModelCandidate,
    ModelCatalogDelta, ReviewConfig, ReviewerArtifact, ReviewerConfig, ReviewerStatus,
    StaleModelFinding, HARNESS_MODEL_EVALUATION_REPORT_VERSION, REVIEW_CONFIG_VERSION,
};
use std::collections::BTreeMap;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HarnessProbe {
    pub harness_id: String,
    pub available: bool,
    pub version: Option<String>,
    pub path: Option<String>,
    pub failure_reason: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct HarnessModelEvaluationOutput {
    pub report: HarnessModelEvaluationReport,
    pub transcripts: Vec<(String, String)>,
}

pub fn evaluate_harness_model_matrix(
    suite: &EvalTaskSuite,
    matrix: &HarnessModelMatrix,
    probes: &[HarnessProbe],
    stale_model_findings: Vec<StaleModelFinding>,
) -> Result<HarnessModelEvaluationOutput, CoreError> {
    suite.validate()?;
    matrix.validate()?;

    let probe_by_harness = probes
        .iter()
        .map(|probe| (probe.harness_id.as_str(), probe))
        .collect::<BTreeMap<_, _>>();
    let mut cells = Vec::new();
    let mut transcripts = Vec::new();

    for harness in &matrix.harnesses {
        let probe = probe_by_harness.get(harness.harness_id.as_str()).copied();
        for model in &matrix.models {
            for task in &suite.tasks {
                let cell = match probe {
                    Some(probe) if probe.available => evaluate_cell(harness, model, task)?,
                    Some(probe) => unavailable_cell(harness, model, task, probe),
                    None => unavailable_cell(
                        harness,
                        model,
                        task,
                        &HarnessProbe {
                            harness_id: harness.harness_id.clone(),
                            available: false,
                            version: None,
                            path: None,
                            failure_reason: Some("harness was not probed".to_string()),
                        },
                    ),
                };
                transcripts.push((
                    cell.transcript_path.clone(),
                    transcript_for_cell(&cell, probe),
                ));
                cells.push(cell);
            }
        }
    }

    let summary = summarize_cells(&cells);
    let report = HarnessModelEvaluationReport {
        schema_version: HARNESS_MODEL_EVALUATION_REPORT_VERSION.to_string(),
        report_id: format!("{}-{}", matrix.matrix_id, suite.suite_id),
        generated_at: matrix.observed_at.clone(),
        suite_id: suite.suite_id.clone(),
        matrix_id: matrix.matrix_id.clone(),
        summary,
        cells,
        stale_model_findings,
        catalog_deltas: catalog_deltas(matrix),
    };
    report.validate()?;

    Ok(HarnessModelEvaluationOutput {
        report,
        transcripts,
    })
}

fn evaluate_cell(
    harness: &HarnessProfile,
    model: &ModelCandidate,
    task: &EvalTask,
) -> Result<HarnessModelEvaluationCell, CoreError> {
    let config = ReviewConfig {
        schema_version: REVIEW_CONFIG_VERSION.to_string(),
        config_id: format!("eval-{}-{}", harness.harness_id, model.model_id),
        reviewers: vec![ReviewerConfig {
            id: format!("{}-{}", harness.harness_id, task.task_id),
            perspective: "evaluation".to_string(),
            model: model.model_id.clone(),
            fake_behavior: FakeReviewerBehavior::Directive,
        }],
        confidence_min: 0.7,
    };
    let run = review(&task.review_request, &config)?;
    let mut artifact = run
        .reviewer_artifacts
        .into_iter()
        .next()
        .expect("single-reviewer config produces one reviewer artifact");
    let cost_usd = estimate_cost_usd(&artifact, model);
    artifact.cost_usd = cost_usd;
    let artifact_valid = artifact.validate().is_ok();
    let degraded = artifact.status != ReviewerStatus::Completed;
    let (found, false_positives, fixture_score) = grade_artifact(&artifact, task);
    let score = if degraded { 0.0 } else { fixture_score };
    let status = cell_status(
        EvalExecutionMode::OfflineContract,
        task,
        artifact_valid,
        degraded,
        false_positives,
        score,
    );
    let failure_reason = if degraded {
        artifact
            .degraded_reason
            .clone()
            .or_else(|| Some("reviewer degraded".to_string()))
    } else {
        None
    };

    Ok(HarnessModelEvaluationCell {
        cell_id: cell_id(&harness.harness_id, &model.model_id, &task.task_id),
        harness_id: harness.harness_id.clone(),
        model_id: model.model_id.clone(),
        task_id: task.task_id.clone(),
        execution_mode: EvalExecutionMode::OfflineContract,
        status,
        artifact_valid,
        reviewer_artifact: Some(artifact),
        expected_findings_found: found,
        expected_findings_total: task.expected_findings.len() as u64,
        false_positives,
        score,
        latency_ms: 0,
        cost_usd,
        degraded,
        transcript_path: transcript_path(&harness.harness_id, &model.model_id, &task.task_id),
        failure_reason,
    })
}

fn unavailable_cell(
    harness: &HarnessProfile,
    model: &ModelCandidate,
    task: &EvalTask,
    probe: &HarnessProbe,
) -> HarnessModelEvaluationCell {
    HarnessModelEvaluationCell {
        cell_id: cell_id(&harness.harness_id, &model.model_id, &task.task_id),
        harness_id: harness.harness_id.clone(),
        model_id: model.model_id.clone(),
        task_id: task.task_id.clone(),
        execution_mode: EvalExecutionMode::OfflineContract,
        status: EvalCellStatus::Unavailable,
        artifact_valid: false,
        reviewer_artifact: None,
        expected_findings_found: 0,
        expected_findings_total: task.expected_findings.len() as u64,
        false_positives: 0,
        score: 0.0,
        latency_ms: 0,
        cost_usd: 0.0,
        degraded: false,
        transcript_path: transcript_path(&harness.harness_id, &model.model_id, &task.task_id),
        failure_reason: probe
            .failure_reason
            .clone()
            .or_else(|| Some("harness unavailable".to_string())),
    }
}

fn cell_status(
    execution_mode: EvalExecutionMode,
    task: &EvalTask,
    artifact_valid: bool,
    degraded: bool,
    false_positives: u64,
    score: f64,
) -> EvalCellStatus {
    if !artifact_valid {
        return EvalCellStatus::Fail;
    }
    if degraded {
        return if task.expected_degraded {
            EvalCellStatus::Degraded
        } else {
            EvalCellStatus::Fail
        };
    }
    if score < task.min_score || false_positives > task.max_false_positives {
        return EvalCellStatus::Fail;
    }
    match execution_mode {
        EvalExecutionMode::OfflineContract => EvalCellStatus::Warn,
        EvalExecutionMode::LiveHarness => EvalCellStatus::Pass,
    }
}

fn grade_artifact(artifact: &ReviewerArtifact, task: &EvalTask) -> (u64, u64, f64) {
    let mut matched = vec![false; task.expected_findings.len()];
    let mut false_positives = 0;

    for finding in &artifact.findings {
        if let Some(index) =
            task.expected_findings
                .iter()
                .enumerate()
                .find_map(|(index, expected)| {
                    if !matched[index] && finding_matches(expected, finding) {
                        Some(index)
                    } else {
                        None
                    }
                })
        {
            matched[index] = true;
        } else {
            false_positives += 1;
        }
    }

    let found = matched.iter().filter(|value| **value).count() as u64;
    let score = if task.expected_findings.is_empty() {
        if false_positives == 0 {
            1.0
        } else {
            0.0
        }
    } else {
        found as f64 / task.expected_findings.len() as f64
    };

    (found, false_positives, score)
}

fn finding_matches(expected: &ExpectedFinding, finding: &cerberus_schema::Finding) -> bool {
    expected.matches(finding)
}

fn summarize_cells(cells: &[HarnessModelEvaluationCell]) -> HarnessModelEvaluationSummary {
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
    let average_score = if cells.is_empty() {
        0.0
    } else {
        cells.iter().map(|cell| cell.score).sum::<f64>() / cells.len() as f64
    };

    HarnessModelEvaluationSummary {
        total_cells,
        valid_artifacts,
        warn_cells,
        unavailable_cells,
        degraded_cells,
        failed_cells,
        average_score,
    }
}

fn estimate_cost_usd(artifact: &ReviewerArtifact, model: &ModelCandidate) -> f64 {
    let input = artifact.usage.prompt_tokens as f64 * model.input_usd_per_m / 1_000_000.0;
    let output = artifact.usage.completion_tokens as f64 * model.output_usd_per_m / 1_000_000.0;
    input + output
}

fn catalog_deltas(matrix: &HarnessModelMatrix) -> Vec<ModelCatalogDelta> {
    let mut deltas = Vec::new();
    for model in &matrix.models {
        let Some(previous) = &model.previous else {
            continue;
        };
        push_delta(
            &mut deltas,
            &model.model_id,
            "context_length",
            previous.context_length.to_string(),
            model.context_length.to_string(),
        );
        push_delta(
            &mut deltas,
            &model.model_id,
            "max_completion_tokens",
            previous.max_completion_tokens.to_string(),
            model.max_completion_tokens.to_string(),
        );
        push_delta(
            &mut deltas,
            &model.model_id,
            "input_usd_per_m",
            money(previous.input_usd_per_m),
            money(model.input_usd_per_m),
        );
        push_delta(
            &mut deltas,
            &model.model_id,
            "output_usd_per_m",
            money(previous.output_usd_per_m),
            money(model.output_usd_per_m),
        );
        if previous.cache_read_usd_per_m != model.cache_read_usd_per_m {
            deltas.push(ModelCatalogDelta {
                model_id: model.model_id.clone(),
                field: "cache_read_usd_per_m".to_string(),
                previous: previous
                    .cache_read_usd_per_m
                    .map(money)
                    .unwrap_or_else(|| "none".to_string()),
                current: model
                    .cache_read_usd_per_m
                    .map(money)
                    .unwrap_or_else(|| "none".to_string()),
            });
        }
    }
    deltas
}

fn push_delta(
    deltas: &mut Vec<ModelCatalogDelta>,
    model_id: &str,
    field: &str,
    previous: String,
    current: String,
) {
    if previous != current {
        deltas.push(ModelCatalogDelta {
            model_id: model_id.to_string(),
            field: field.to_string(),
            previous,
            current,
        });
    }
}

fn money(value: f64) -> String {
    format!("{value:.6}")
}

fn transcript_for_cell(cell: &HarnessModelEvaluationCell, probe: Option<&HarnessProbe>) -> String {
    let mut out = String::new();
    out.push_str(&format!("cell_id: {}\n", cell.cell_id));
    out.push_str(&format!("harness: {}\n", cell.harness_id));
    out.push_str(&format!("model: {}\n", cell.model_id));
    out.push_str(&format!("task: {}\n", cell.task_id));
    out.push_str(&format!("status: {:?}\n", cell.status));
    if let Some(probe) = probe {
        out.push_str(&format!("harness_available: {}\n", probe.available));
        if let Some(version) = &probe.version {
            out.push_str(&format!("harness_version: {version}\n"));
        }
        if let Some(path) = &probe.path {
            out.push_str(&format!("harness_path: {path}\n"));
        }
    }
    if let Some(reason) = &cell.failure_reason {
        out.push_str(&format!("failure_reason: {reason}\n"));
    }
    out.push_str(&format!("artifact_valid: {}\n", cell.artifact_valid));
    out.push_str(&format!("score: {:.3}\n", cell.score));
    out.push_str(&format!("false_positives: {}\n", cell.false_positives));
    out
}

fn transcript_path(harness_id: &str, model_id: &str, task_id: &str) -> String {
    format!("transcripts/{}.txt", cell_id(harness_id, model_id, task_id))
}

fn cell_id(harness_id: &str, model_id: &str, task_id: &str) -> String {
    sanitize(&format!("{harness_id}__{model_id}__{task_id}"))
}

fn sanitize(value: &str) -> String {
    value
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || character == '-' || character == '_' {
                character
            } else {
                '_'
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use cerberus_schema::{
        Change, ChangedFile, EvalTask, EvalTaskSuite, ExpectedFinding, FileStatus,
        HarnessModelMatrix, HarnessProfile, ModelCandidate, ReviewContext, ReviewRequest,
        ReviewSource, Severity, EVAL_TASK_SUITE_VERSION, HARNESS_MODEL_MATRIX_VERSION,
        HARNESS_PROFILE_VERSION, MODEL_CANDIDATE_VERSION, REVIEW_REQUEST_VERSION,
    };
    use std::collections::BTreeMap;

    #[test]
    fn harness_model_eval_grades_fixture_artifacts_and_drift() {
        let suite = suite();
        let matrix = matrix();
        let probes = vec![HarnessProbe {
            harness_id: "pi".to_string(),
            available: true,
            version: Some("0.78.1".to_string()),
            path: Some("/bin/pi".to_string()),
            failure_reason: None,
        }];

        let output =
            evaluate_harness_model_matrix(&suite, &matrix, &probes, vec![]).expect("eval passes");

        output.report.validate().expect("report validates");
        assert_eq!(output.report.summary.total_cells, 2);
        assert_eq!(output.report.summary.valid_artifacts, 2);
        assert_eq!(output.report.summary.failed_cells, 0);
        assert!(!output.report.catalog_deltas.is_empty());
        assert!(output
            .report
            .cells
            .iter()
            .any(|cell| cell.task_id == "seeded-bug" && cell.expected_findings_found == 1));
        assert_eq!(output.transcripts.len(), 2);
    }

    #[test]
    fn harness_model_eval_unavailable_harness_is_structured_failure_not_crash() {
        let suite = suite();
        let matrix = matrix();
        let probes = vec![HarnessProbe {
            harness_id: "pi".to_string(),
            available: false,
            version: None,
            path: None,
            failure_reason: Some("not installed".to_string()),
        }];

        let output =
            evaluate_harness_model_matrix(&suite, &matrix, &probes, vec![]).expect("eval passes");

        assert_eq!(output.report.summary.unavailable_cells, 2);
        assert!(output
            .report
            .cells
            .iter()
            .all(|cell| cell.status == EvalCellStatus::Unavailable));
    }

    fn suite() -> EvalTaskSuite {
        EvalTaskSuite {
            schema_version: EVAL_TASK_SUITE_VERSION.to_string(),
            suite_id: "unit-suite".to_string(),
            description: None,
            tasks: vec![clean_task(), seeded_task()],
        }
    }

    fn matrix() -> HarnessModelMatrix {
        HarnessModelMatrix {
            schema_version: HARNESS_MODEL_MATRIX_VERSION.to_string(),
            matrix_id: "unit-matrix".to_string(),
            observed_at: "2026-06-18".to_string(),
            harnesses: vec![HarnessProfile {
                schema_version: HARNESS_PROFILE_VERSION.to_string(),
                harness_id: "pi".to_string(),
                command: "pi".to_string(),
                version: None,
                path: None,
                notes: None,
            }],
            models: vec![ModelCandidate {
                schema_version: MODEL_CANDIDATE_VERSION.to_string(),
                model_id: "fake/model".to_string(),
                provider: "fake".to_string(),
                context_length: 128_000,
                max_completion_tokens: 16_384,
                input_usd_per_m: 1.0,
                output_usd_per_m: 2.0,
                cache_read_usd_per_m: None,
                supported_parameters: vec!["structured_outputs".to_string()],
                catalog_source: "fixture".to_string(),
                catalog_observed_at: "2026-06-18".to_string(),
                previous: Some(cerberus_schema::ModelCatalogSnapshot {
                    observed_at: "2026-06-17".to_string(),
                    context_length: 64_000,
                    max_completion_tokens: 8_192,
                    input_usd_per_m: 1.0,
                    output_usd_per_m: 2.0,
                    cache_read_usd_per_m: None,
                }),
            }],
            stale_model_patterns: vec![],
            drift_scan_paths: vec![],
        }
    }

    fn clean_task() -> EvalTask {
        EvalTask {
            task_id: "clean".to_string(),
            review_request: request("clean", "diff --git a/src/lib.rs b/src/lib.rs\n"),
            expected_findings: vec![],
            tags: vec!["clean".to_string()],
            expected_degraded: false,
            min_score: 1.0,
            max_false_positives: 0,
        }
    }

    fn seeded_task() -> EvalTask {
        EvalTask {
            task_id: "seeded-bug".to_string(),
            review_request: request(
                "seeded-bug",
                "diff --git a/src/lib.rs b/src/lib.rs\n+CERBERUS_FAKE_FINDING\n",
            ),
            expected_findings: vec![ExpectedFinding {
                category: "fixture".to_string(),
                severity: Severity::Major,
                path: "src/lib.rs".to_string(),
                line: Some(1),
                evidence: "CERBERUS_FAKE_FINDING".to_string(),
            }],
            tags: vec!["seeded_bug".to_string()],
            expected_degraded: false,
            min_score: 1.0,
            max_false_positives: 0,
        }
    }

    fn request(id: &str, diff: &str) -> ReviewRequest {
        ReviewRequest {
            schema_version: REVIEW_REQUEST_VERSION.to_string(),
            request_id: format!("eval-{id}"),
            source: ReviewSource::Fixture {
                name: id.to_string(),
            },
            change: Change {
                title: id.to_string(),
                description: None,
                base_ref: None,
                head_ref: None,
                head_sha: Some(format!("{id}-sha")),
                diff: diff.to_string(),
                files: vec![ChangedFile {
                    path: "src/lib.rs".to_string(),
                    status: FileStatus::Modified,
                    additions: 1,
                    deletions: 0,
                }],
            },
            context: ReviewContext {
                summary: None,
                acceptance: vec![],
                linked_artifacts: vec![],
                metadata: BTreeMap::new(),
            },
            caller: Default::default(),
            policy: Default::default(),
        }
    }
}
