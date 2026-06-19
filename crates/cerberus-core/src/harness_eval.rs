use crate::{
    default_config, digest_json, review, validate_reviewer_artifact_for_request,
    validate_reviewer_config_packet, CoreError,
};
use cerberus_schema::{
    CostEnvelope, EvalCellStatus, EvalExecutionMode, EvalReadinessCell, EvalReadinessReport,
    EvalReadinessSummary, EvalTask, EvalTaskSuite, ExpectedFinding, FakeReviewerBehavior,
    GateResult, GateStatus, HarnessModelEvaluationCell, HarnessModelEvaluationReport,
    HarnessModelEvaluationSummary, HarnessModelMatrix, HarnessProfile, ModelCandidate,
    ModelCatalogDelta, PeerHarnessCommandProfiles, PromotionGate, PromotionStatus, ReviewConfig,
    ReviewerArtifact, ReviewerConfig, ReviewerConfigBenchmark, ReviewerConfigPacket,
    ReviewerConfigProducer, ReviewerHarnessMetadata, ReviewerModelMetadata, ReviewerStatus,
    RollbackMetadata, ScoreDistribution, StaleModelFinding, EVAL_READINESS_REPORT_VERSION,
    HARNESS_MODEL_EVALUATION_REPORT_VERSION, REVIEWER_CONFIG_PACKET_VERSION, REVIEW_CONFIG_VERSION,
};
use std::collections::{BTreeMap, BTreeSet};

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

const LIVE_TRANSCRIPT_ARTIFACT_BEGIN_MARKER: &str = "CERBERUS_REVIEWER_ARTIFACT_JSON_BEGIN";
const LIVE_TRANSCRIPT_ARTIFACT_END_MARKER: &str = "CERBERUS_REVIEWER_ARTIFACT_JSON_END";

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

    harness_model_evaluation_output(suite, matrix, cells, transcripts, stale_model_findings)
}

pub fn harness_model_evaluation_output(
    suite: &EvalTaskSuite,
    matrix: &HarnessModelMatrix,
    cells: Vec<HarnessModelEvaluationCell>,
    transcripts: Vec<(String, String)>,
    stale_model_findings: Vec<StaleModelFinding>,
) -> Result<HarnessModelEvaluationOutput, CoreError> {
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

pub fn harness_model_readiness_report(
    suite: &EvalTaskSuite,
    matrix: &HarnessModelMatrix,
    probes: &[HarnessProbe],
    peer_runner_probes: &[HarnessProbe],
    peer_profiles: &PeerHarnessCommandProfiles,
    available_env: &BTreeSet<String>,
    provider_budget_acknowledged: bool,
) -> Result<EvalReadinessReport, CoreError> {
    suite.validate()?;
    matrix.validate()?;
    peer_profiles.validate()?;

    let probe_by_harness = probes
        .iter()
        .map(|probe| (probe.harness_id.as_str(), probe))
        .collect::<BTreeMap<_, _>>();
    let profile_by_harness = peer_profiles
        .profiles
        .iter()
        .map(|profile| (profile.harness_id.as_str(), profile))
        .collect::<BTreeMap<_, _>>();
    let peer_runner_probe_by_harness = peer_runner_probes
        .iter()
        .map(|probe| (probe.harness_id.as_str(), probe))
        .collect::<BTreeMap<_, _>>();
    let mut cells = Vec::new();

    for harness in &matrix.harnesses {
        let probe = probe_by_harness.get(harness.harness_id.as_str()).copied();
        let profile = profile_by_harness.get(harness.harness_id.as_str()).copied();
        let peer_runner_probe = peer_runner_probe_by_harness
            .get(harness.harness_id.as_str())
            .copied();
        for model in &matrix.models {
            for task in &suite.tasks {
                let mut blockers = Vec::new();
                let (harness_available, harness_version, harness_path) = match probe {
                    Some(probe) if probe.available => {
                        (true, probe.version.clone(), probe.path.clone())
                    }
                    Some(probe) => {
                        blockers.push(format!(
                            "harness unavailable: {}",
                            probe
                                .failure_reason
                                .as_deref()
                                .unwrap_or("harness probe failed")
                        ));
                        (false, probe.version.clone(), probe.path.clone())
                    }
                    None => {
                        blockers.push("harness was not probed".to_string());
                        (false, None, None)
                    }
                };
                let (peer_profile_found, env_required, requires_provider_budget_ack) = match profile
                {
                    Some(profile) => (
                        true,
                        profile.env_required.clone(),
                        profile.requires_provider_budget_ack,
                    ),
                    None => {
                        blockers.push("peer harness profile missing".to_string());
                        (false, Vec::new(), false)
                    }
                };
                let (peer_runner_available, peer_runner_path) = match (profile, peer_runner_probe) {
                    (Some(_), Some(probe)) if probe.available => (true, probe.path.clone()),
                    (Some(_), Some(probe)) => {
                        blockers.push(format!(
                            "peer harness runner unavailable: {}",
                            probe
                                .failure_reason
                                .as_deref()
                                .unwrap_or("peer harness runner probe failed")
                        ));
                        (false, probe.path.clone())
                    }
                    (Some(_), None) => {
                        blockers.push("peer harness runner was not probed".to_string());
                        (false, None)
                    }
                    (None, _) => (false, None),
                };
                let env_missing = env_required
                    .iter()
                    .filter(|name| !available_env.contains(*name))
                    .cloned()
                    .collect::<Vec<_>>();
                if !env_missing.is_empty() {
                    blockers.push(format!(
                        "missing environment variable(s): {}",
                        env_missing.join(", ")
                    ));
                }
                if requires_provider_budget_ack && !provider_budget_acknowledged {
                    blockers.push(
                        "provider budget acknowledgement missing: CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK"
                            .to_string(),
                    );
                }

                cells.push(EvalReadinessCell {
                    cell_id: cell_id(&harness.harness_id, &model.model_id, &task.task_id),
                    harness_id: harness.harness_id.clone(),
                    model_id: model.model_id.clone(),
                    task_id: task.task_id.clone(),
                    harness_available,
                    harness_version,
                    harness_path,
                    peer_profile_found,
                    peer_runner_available,
                    peer_runner_path,
                    env_required,
                    env_missing,
                    requires_provider_budget_ack,
                    provider_budget_acknowledged,
                    runnable: blockers.is_empty(),
                    blockers,
                });
            }
        }
    }

    let summary = EvalReadinessSummary {
        total_cells: cells.len() as u64,
        runnable_cells: cells.iter().filter(|cell| cell.runnable).count() as u64,
        unavailable_harness_cells: cells.iter().filter(|cell| !cell.harness_available).count()
            as u64,
        unavailable_peer_runner_cells: cells
            .iter()
            .filter(|cell| cell.peer_profile_found && !cell.peer_runner_available)
            .count() as u64,
        missing_profile_cells: cells.iter().filter(|cell| !cell.peer_profile_found).count() as u64,
        missing_env_cells: cells
            .iter()
            .filter(|cell| !cell.env_missing.is_empty())
            .count() as u64,
        budget_blocked_cells: cells
            .iter()
            .filter(|cell| cell.requires_provider_budget_ack && !cell.provider_budget_acknowledged)
            .count() as u64,
    };
    let report = EvalReadinessReport {
        schema_version: EVAL_READINESS_REPORT_VERSION.to_string(),
        report_id: format!("{}-{}-readiness", matrix.matrix_id, suite.suite_id),
        generated_at: matrix.observed_at.clone(),
        suite_id: suite.suite_id.clone(),
        matrix_id: matrix.matrix_id.clone(),
        peer_profiles_observed_at: Some(peer_profiles.observed_at.clone()),
        summary,
        cells,
    };
    report.validate()?;
    Ok(report)
}

pub fn eval_reviewer_config(
    harness: &HarnessProfile,
    model: &ModelCandidate,
    task: &EvalTask,
) -> ReviewerConfig {
    ReviewerConfig {
        id: format!("{}-{}", harness.harness_id, task.task_id),
        perspective: "evaluation".to_string(),
        model: model.model_id.clone(),
        fake_behavior: FakeReviewerBehavior::Directive,
    }
}

pub fn reviewer_config_candidate_from_eval_report(
    report: &HarnessModelEvaluationReport,
    matrix: &HarnessModelMatrix,
    suite: &EvalTaskSuite,
    transcripts: &BTreeMap<String, String>,
) -> Result<ReviewerConfigPacket, CoreError> {
    report.validate()?;
    matrix.validate()?;
    suite.validate()?;
    if report.matrix_id != matrix.matrix_id {
        return Err(CoreError::EvalReportCandidate(format!(
            "report matrix_id {:?} does not match matrix {:?}",
            report.matrix_id, matrix.matrix_id
        )));
    }
    if report.suite_id != suite.suite_id {
        return Err(CoreError::EvalReportCandidate(format!(
            "report suite_id {:?} does not match suite {:?}",
            report.suite_id, suite.suite_id
        )));
    }

    let harness_by_id = matrix
        .harnesses
        .iter()
        .map(|harness| (harness.harness_id.as_str(), harness))
        .collect::<BTreeMap<_, _>>();
    let model_by_id = matrix
        .models
        .iter()
        .map(|model| (model.model_id.as_str(), model))
        .collect::<BTreeMap<_, _>>();
    let required_task_ids = suite
        .tasks
        .iter()
        .map(|task| task.task_id.as_str())
        .collect::<BTreeSet<_>>();
    let task_by_id = suite
        .tasks
        .iter()
        .map(|task| (task.task_id.as_str(), task))
        .collect::<BTreeMap<_, _>>();
    let mut cells_by_pair = BTreeMap::<(String, String), Vec<&HarnessModelEvaluationCell>>::new();

    for cell in &report.cells {
        if !harness_by_id.contains_key(cell.harness_id.as_str()) {
            return Err(CoreError::EvalReportCandidate(format!(
                "cell {:?} references unknown harness {:?}",
                cell.cell_id, cell.harness_id
            )));
        }
        if !model_by_id.contains_key(cell.model_id.as_str()) {
            return Err(CoreError::EvalReportCandidate(format!(
                "cell {:?} references unknown model {:?}",
                cell.cell_id, cell.model_id
            )));
        }
        if !task_by_id.contains_key(cell.task_id.as_str()) {
            return Err(CoreError::EvalReportCandidate(format!(
                "cell {:?} references unknown task {:?}",
                cell.cell_id, cell.task_id
            )));
        }
        cells_by_pair
            .entry((cell.harness_id.clone(), cell.model_id.clone()))
            .or_default()
            .push(cell);
    }

    let mut candidates = Vec::new();
    for ((harness_id, model_id), cells) in cells_by_pair {
        if !covers_required_tasks(&cells, &required_task_ids)
            || !cells.iter().all(|cell| candidate_cell_claims_pass(cell))
        {
            continue;
        }
        let harness = harness_by_id[harness_id.as_str()];
        let model = model_by_id[model_id.as_str()];
        for cell in &cells {
            let task = task_by_id[cell.task_id.as_str()];
            verify_regraded_candidate_cell(cell, harness, model, task, transcripts)?;
        }
        candidates.push(EvalWinner {
            harness,
            model,
            cells,
        });
    }

    candidates.sort_by(|left, right| {
        right
            .cells
            .len()
            .cmp(&left.cells.len())
            .then_with(|| right.mean_score().total_cmp(&left.mean_score()))
            .then_with(|| {
                left.measured_cost_usd()
                    .total_cmp(&right.measured_cost_usd())
            })
            .then_with(|| {
                left.measured_wall_sec()
                    .total_cmp(&right.measured_wall_sec())
            })
            .then_with(|| left.harness.harness_id.cmp(&right.harness.harness_id))
            .then_with(|| left.model.model_id.cmp(&right.model.model_id))
    });
    let winner = candidates.into_iter().next().ok_or_else(|| {
        CoreError::EvalReportCandidate(
            "no fully passing live_harness harness/model group found".to_string(),
        )
    })?;

    reviewer_config_packet_for_winner(report, &winner)
}

fn covers_required_tasks(
    cells: &[&HarnessModelEvaluationCell],
    required_task_ids: &BTreeSet<&str>,
) -> bool {
    if cells.len() != required_task_ids.len() {
        return false;
    }
    let observed = cells
        .iter()
        .map(|cell| cell.task_id.as_str())
        .collect::<BTreeSet<_>>();
    observed == *required_task_ids
}

fn candidate_cell_claims_pass(cell: &HarnessModelEvaluationCell) -> bool {
    cell.execution_mode == EvalExecutionMode::LiveHarness
        && cell.status == EvalCellStatus::Pass
        && cell.artifact_valid
        && !cell.degraded
        && cell.false_positives == 0
}

fn verify_regraded_candidate_cell(
    cell: &HarnessModelEvaluationCell,
    harness: &HarnessProfile,
    model: &ModelCandidate,
    task: &EvalTask,
    transcripts: &BTreeMap<String, String>,
) -> Result<(), CoreError> {
    let artifact = cell.reviewer_artifact.clone().ok_or_else(|| {
        CoreError::EvalReportCandidate(format!(
            "cell {:?} claims pass but has no reviewer artifact",
            cell.cell_id
        ))
    })?;
    verify_live_transcript_artifact(cell, &artifact, transcripts)?;
    let regraded = evaluate_harness_model_artifact(
        harness,
        model,
        task,
        cell.execution_mode,
        artifact,
        cell.latency_ms,
        cell.transcript_path.clone(),
    )?;
    if !candidate_cell_claims_pass(&regraded) {
        return Err(CoreError::EvalReportCandidate(format!(
            "cell {:?} regraded as {:?}, not pass",
            cell.cell_id, regraded.status
        )));
    }
    if !regraded_cell_matches_report(cell, &regraded) {
        return Err(CoreError::EvalReportCandidate(format!(
            "cell {:?} report fields do not match regraded reviewer artifact",
            cell.cell_id
        )));
    }
    Ok(())
}

fn verify_live_transcript_artifact(
    cell: &HarnessModelEvaluationCell,
    artifact: &ReviewerArtifact,
    transcripts: &BTreeMap<String, String>,
) -> Result<(), CoreError> {
    let transcript = transcripts.get(&cell.transcript_path).ok_or_else(|| {
        CoreError::EvalReportCandidate(format!(
            "cell {:?} missing live transcript {:?}",
            cell.cell_id, cell.transcript_path
        ))
    })?;
    let transcript_artifact = reviewer_artifact_from_live_transcript(transcript)?;
    if &transcript_artifact != artifact {
        return Err(CoreError::EvalReportCandidate(format!(
            "cell {:?} transcript artifact does not match report artifact",
            cell.cell_id
        )));
    }
    Ok(())
}

fn reviewer_artifact_from_live_transcript(transcript: &str) -> Result<ReviewerArtifact, CoreError> {
    let begin_count = transcript
        .matches(LIVE_TRANSCRIPT_ARTIFACT_BEGIN_MARKER)
        .count();
    if begin_count != 1 {
        return Err(CoreError::EvalReportCandidate(format!(
            "live transcript must contain exactly one {LIVE_TRANSCRIPT_ARTIFACT_BEGIN_MARKER} marker, found {begin_count}"
        )));
    }
    let end_count = transcript
        .matches(LIVE_TRANSCRIPT_ARTIFACT_END_MARKER)
        .count();
    if end_count != 1 {
        return Err(CoreError::EvalReportCandidate(format!(
            "live transcript must contain exactly one {LIVE_TRANSCRIPT_ARTIFACT_END_MARKER} marker, found {end_count}"
        )));
    }

    let (_, after_begin) = transcript
        .split_once(LIVE_TRANSCRIPT_ARTIFACT_BEGIN_MARKER)
        .ok_or_else(|| {
            CoreError::EvalReportCandidate(
                "live transcript artifact begin marker was missing".to_string(),
            )
        })?;
    let (json, _) = after_begin
        .split_once(LIVE_TRANSCRIPT_ARTIFACT_END_MARKER)
        .ok_or_else(|| {
            CoreError::EvalReportCandidate(
                "live transcript artifact end marker appeared before begin marker".to_string(),
            )
        })?;
    let json = json.trim();
    if json.is_empty() {
        return Err(CoreError::EvalReportCandidate(
            "live transcript artifact JSON block was empty".to_string(),
        ));
    }

    serde_json::from_str(json).map_err(|error| {
        CoreError::EvalReportCandidate(format!(
            "live transcript artifact JSON was not ReviewerArtifact.v1: {error}"
        ))
    })
}

fn regraded_cell_matches_report(
    reported: &HarnessModelEvaluationCell,
    regraded: &HarnessModelEvaluationCell,
) -> bool {
    reported.cell_id == regraded.cell_id
        && reported.harness_id == regraded.harness_id
        && reported.model_id == regraded.model_id
        && reported.task_id == regraded.task_id
        && reported.execution_mode == regraded.execution_mode
        && reported.status == regraded.status
        && reported.artifact_valid == regraded.artifact_valid
        && reported.expected_findings_found == regraded.expected_findings_found
        && reported.expected_findings_total == regraded.expected_findings_total
        && reported.false_positives == regraded.false_positives
        && float_eq(reported.score, regraded.score)
        && float_eq(reported.cost_usd, regraded.cost_usd)
        && reported.degraded == regraded.degraded
}

fn float_eq(left: f64, right: f64) -> bool {
    (left - right).abs() <= 0.000_000_001
}

fn evaluate_cell(
    harness: &HarnessProfile,
    model: &ModelCandidate,
    task: &EvalTask,
) -> Result<HarnessModelEvaluationCell, CoreError> {
    let config = ReviewConfig {
        schema_version: REVIEW_CONFIG_VERSION.to_string(),
        config_id: format!("eval-{}-{}", harness.harness_id, model.model_id),
        reviewers: vec![eval_reviewer_config(harness, model, task)],
        confidence_min: 0.7,
    };
    let run = review(&task.review_request, &config)?;
    let artifact = run
        .reviewer_artifacts
        .into_iter()
        .next()
        .expect("single-reviewer config produces one reviewer artifact");

    evaluate_harness_model_artifact(
        harness,
        model,
        task,
        EvalExecutionMode::OfflineContract,
        artifact,
        0,
        transcript_path(&harness.harness_id, &model.model_id, &task.task_id),
    )
}

pub fn evaluate_harness_model_artifact(
    harness: &HarnessProfile,
    model: &ModelCandidate,
    task: &EvalTask,
    execution_mode: EvalExecutionMode,
    artifact: ReviewerArtifact,
    latency_ms: u64,
    transcript_path: String,
) -> Result<HarnessModelEvaluationCell, CoreError> {
    let reviewer = eval_reviewer_config(harness, model, task);
    let mut artifact =
        match validate_reviewer_artifact_for_request(&reviewer, &task.review_request, artifact) {
            Ok(artifact) => artifact,
            Err(error) => {
                return Ok(failed_harness_model_cell(
                    harness,
                    model,
                    task,
                    execution_mode,
                    latency_ms,
                    transcript_path,
                    format!("invalid reviewer artifact: {error}"),
                ));
            }
        };
    let cost_usd = if artifact.cost_usd > 0.0 {
        artifact.cost_usd
    } else {
        estimate_cost_usd(&artifact, model)
    };
    artifact.cost_usd = cost_usd;
    let degraded = artifact.status != ReviewerStatus::Completed;
    let (found, false_positives, fixture_score) = grade_artifact(&artifact, task);
    let score = if degraded { 0.0 } else { fixture_score };
    let status = cell_status(execution_mode, task, true, degraded, false_positives, score);
    let failure_reason = if degraded {
        artifact
            .degraded_reason
            .clone()
            .or_else(|| Some("reviewer degraded".to_string()))
    } else if status == EvalCellStatus::Fail {
        Some("artifact did not meet eval rubric".to_string())
    } else {
        None
    };

    Ok(HarnessModelEvaluationCell {
        cell_id: cell_id(&harness.harness_id, &model.model_id, &task.task_id),
        harness_id: harness.harness_id.clone(),
        model_id: model.model_id.clone(),
        task_id: task.task_id.clone(),
        execution_mode,
        status,
        artifact_valid: true,
        reviewer_artifact: Some(artifact),
        expected_findings_found: found,
        expected_findings_total: task.expected_findings.len() as u64,
        false_positives,
        score,
        latency_ms,
        cost_usd,
        degraded,
        transcript_path,
        failure_reason,
    })
}

pub fn unavailable_harness_model_cell(
    harness: &HarnessProfile,
    model: &ModelCandidate,
    task: &EvalTask,
    execution_mode: EvalExecutionMode,
    transcript_path: String,
    failure_reason: String,
) -> HarnessModelEvaluationCell {
    HarnessModelEvaluationCell {
        cell_id: cell_id(&harness.harness_id, &model.model_id, &task.task_id),
        harness_id: harness.harness_id.clone(),
        model_id: model.model_id.clone(),
        task_id: task.task_id.clone(),
        execution_mode,
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
        transcript_path,
        failure_reason: Some(failure_reason),
    }
}

fn unavailable_cell(
    harness: &HarnessProfile,
    model: &ModelCandidate,
    task: &EvalTask,
    probe: &HarnessProbe,
) -> HarnessModelEvaluationCell {
    unavailable_harness_model_cell(
        harness,
        model,
        task,
        EvalExecutionMode::OfflineContract,
        transcript_path(&harness.harness_id, &model.model_id, &task.task_id),
        probe
            .failure_reason
            .clone()
            .unwrap_or_else(|| "harness unavailable".to_string()),
    )
}

fn failed_harness_model_cell(
    harness: &HarnessProfile,
    model: &ModelCandidate,
    task: &EvalTask,
    execution_mode: EvalExecutionMode,
    latency_ms: u64,
    transcript_path: String,
    failure_reason: String,
) -> HarnessModelEvaluationCell {
    HarnessModelEvaluationCell {
        cell_id: cell_id(&harness.harness_id, &model.model_id, &task.task_id),
        harness_id: harness.harness_id.clone(),
        model_id: model.model_id.clone(),
        task_id: task.task_id.clone(),
        execution_mode,
        status: EvalCellStatus::Fail,
        artifact_valid: false,
        reviewer_artifact: None,
        expected_findings_found: 0,
        expected_findings_total: task.expected_findings.len() as u64,
        false_positives: 0,
        score: 0.0,
        latency_ms,
        cost_usd: 0.0,
        degraded: false,
        transcript_path,
        failure_reason: Some(failure_reason),
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

struct EvalWinner<'a> {
    harness: &'a HarnessProfile,
    model: &'a ModelCandidate,
    cells: Vec<&'a HarnessModelEvaluationCell>,
}

impl EvalWinner<'_> {
    fn mean_score(&self) -> f64 {
        self.cells.iter().map(|cell| cell.score).sum::<f64>() / self.cells.len() as f64
    }

    fn measured_cost_usd(&self) -> f64 {
        self.cells.iter().map(|cell| cell.cost_usd).sum()
    }

    fn measured_wall_sec(&self) -> f64 {
        self.cells
            .iter()
            .map(|cell| cell.latency_ms as f64 / 1000.0)
            .sum()
    }
}

fn reviewer_config_packet_for_winner(
    report: &HarnessModelEvaluationReport,
    winner: &EvalWinner<'_>,
) -> Result<ReviewerConfigPacket, CoreError> {
    let provider = normalize_provider(&winner.model.provider);
    let config_model = format!("{}:{}", provider, winner.model.model_id);
    let reviewers = default_candidate_reviewers()
        .iter()
        .map(|(id, perspective)| ReviewerConfig {
            id: (*id).to_string(),
            perspective: (*perspective).to_string(),
            model: config_model.clone(),
            fake_behavior: FakeReviewerBehavior::Directive,
        })
        .collect::<Vec<_>>();
    let config = ReviewConfig {
        schema_version: REVIEW_CONFIG_VERSION.to_string(),
        config_id: format!(
            "eval-candidate-{}",
            sanitize(&format!(
                "{}__{}",
                winner.harness.harness_id, winner.model.model_id
            ))
        ),
        reviewers,
        confidence_min: 0.7,
    };
    let config_hash = digest_json(&config)?;
    let mut prompt_hashes = BTreeMap::new();
    for reviewer in &config.reviewers {
        prompt_hashes.insert(
            reviewer.id.clone(),
            candidate_prompt_hash(report, winner, &reviewer.id)?,
        );
    }
    let models = config
        .reviewers
        .iter()
        .map(|reviewer| ReviewerModelMetadata {
            reviewer_id: reviewer.id.clone(),
            harness_id: winner.harness.harness_id.clone(),
            provider: provider.clone(),
            model: winner.model.model_id.clone(),
            prompt_hash: prompt_hashes[reviewer.id.as_str()].clone(),
            context_length: Some(winner.model.context_length),
        })
        .collect::<Vec<_>>();
    let measured_cost_usd = winner.measured_cost_usd();
    let measured_wall_sec = winner.measured_wall_sec();
    let packet = ReviewerConfigPacket {
        schema_version: REVIEWER_CONFIG_PACKET_VERSION.to_string(),
        packet_id: format!(
            "eval-candidate-{}",
            sanitize(&format!(
                "{}__{}__{}",
                report.report_id, winner.harness.harness_id, winner.model.model_id
            ))
        ),
        producer: ReviewerConfigProducer {
            system: "cerberus-eval-harness".to_string(),
            delivery_id: report.report_id.clone(),
            generated_at: report.generated_at.clone(),
            sandbox_only: true,
            signature: None,
        },
        benchmark: ReviewerConfigBenchmark {
            benchmark_id: report.report_id.clone(),
            suite_id: report.suite_id.clone(),
            arena_version: HARNESS_MODEL_EVALUATION_REPORT_VERSION.to_string(),
            run_id: report.report_id.clone(),
            task_count: winner.cells.len() as u64,
            score_distribution: score_distribution(&winner.cells),
        },
        promotion: PromotionGate {
            status: PromotionStatus::Candidate,
            gates: vec![
                GateResult {
                    name: "live_harness_eval".to_string(),
                    status: GateStatus::Passed,
                    evidence: format!(
                        "{} passed {} live task(s) with mean score {:.3}",
                        winner.harness.harness_id,
                        winner.cells.len(),
                        winner.mean_score()
                    ),
                    waiver: None,
                },
                GateResult {
                    name: "artifact_contract".to_string(),
                    status: GateStatus::Passed,
                    evidence: "every selected cell has artifact_valid=true and status=pass"
                        .to_string(),
                    waiver: None,
                },
                GateResult {
                    name: "sandbox_boundary".to_string(),
                    status: GateStatus::Passed,
                    evidence:
                        "producer.sandbox_only=true; production import still requires approval"
                            .to_string(),
                    waiver: None,
                },
            ],
            rationale: format!(
                "Best fully passing live eval group from {}; sandbox candidate only.",
                report.report_id
            ),
        },
        rollback: RollbackMetadata {
            baseline_config_id: default_config().config_id,
            rollback_command: "restore ReviewConfig.v1 defaults from cerberus-core::default_config"
                .to_string(),
            reason: "Eval-derived candidates must remain reversible until approved.".to_string(),
            previous_packet_id: None,
        },
        cost: CostEnvelope {
            measured_cost_usd,
            max_cost_usd: (measured_cost_usd * 1.25).max(measured_cost_usd + 0.01),
            measured_wall_sec,
            max_wall_sec: (measured_wall_sec * 1.25).max(measured_wall_sec + 1.0),
        },
        harnesses: vec![ReviewerHarnessMetadata {
            harness_id: winner.harness.harness_id.clone(),
            kind: winner.harness.harness_id.clone(),
            provider_name: provider,
            command: winner.harness.command.clone(),
            version: winner.harness.version.clone(),
            execution_mode: "live_harness".to_string(),
        }],
        models,
        prompt_hashes,
        config_hash,
        config,
    };
    validate_reviewer_config_packet(&packet)?;
    Ok(packet)
}

fn default_candidate_reviewers() -> [(&'static str, &'static str); 3] {
    [
        ("correctness", "correctness"),
        ("security", "security"),
        ("testing", "testing"),
    ]
}

fn candidate_prompt_hash(
    report: &HarnessModelEvaluationReport,
    winner: &EvalWinner<'_>,
    reviewer_id: &str,
) -> Result<String, serde_json::Error> {
    let material = serde_json::json!({
        "report_id": report.report_id,
        "suite_id": report.suite_id,
        "matrix_id": report.matrix_id,
        "harness_id": winner.harness.harness_id,
        "model_id": winner.model.model_id,
        "reviewer_id": reviewer_id,
        "prompt_family": "cerberus-reviewer-config-candidate.v1"
    });
    digest_json(&material).map(|digest| format!("sha256:{digest}"))
}

fn score_distribution(cells: &[&HarnessModelEvaluationCell]) -> ScoreDistribution {
    let mut scores = cells.iter().map(|cell| cell.score).collect::<Vec<_>>();
    scores.sort_by(f64::total_cmp);
    let mean = scores.iter().sum::<f64>() / scores.len() as f64;
    let median = if scores.len() % 2 == 0 {
        (scores[scores.len() / 2 - 1] + scores[scores.len() / 2]) / 2.0
    } else {
        scores[scores.len() / 2]
    };
    ScoreDistribution {
        min: scores[0],
        mean,
        median,
        max: scores[scores.len() - 1],
        certified_trials: cells.len() as u64,
    }
}

fn normalize_provider(provider: &str) -> String {
    provider.trim().to_ascii_lowercase()
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

    #[test]
    fn harness_model_eval_grades_external_live_artifact_as_pass() {
        let matrix = matrix();
        let harness = &matrix.harnesses[0];
        let model = &matrix.models[0];
        let task = clean_task();
        let reviewer = eval_reviewer_config(harness, model, &task);
        let config = ReviewConfig {
            schema_version: REVIEW_CONFIG_VERSION.to_string(),
            config_id: "external-live-cell".to_string(),
            reviewers: vec![reviewer],
            confidence_min: 0.7,
        };
        let artifact = crate::review(&task.review_request, &config)
            .expect("fixture review succeeds")
            .reviewer_artifacts
            .into_iter()
            .next()
            .expect("one artifact");

        let cell = evaluate_harness_model_artifact(
            harness,
            model,
            &task,
            EvalExecutionMode::LiveHarness,
            artifact,
            42,
            "transcripts/live.txt".to_string(),
        )
        .expect("live artifact grades");

        assert_eq!(cell.execution_mode, EvalExecutionMode::LiveHarness);
        assert_eq!(cell.status, EvalCellStatus::Pass);
        assert_eq!(cell.latency_ms, 42);
        assert_eq!(cell.transcript_path, "transcripts/live.txt");
    }

    #[test]
    fn harness_model_eval_unavailable_cell_preserves_execution_mode() {
        let matrix = matrix();
        let harness = &matrix.harnesses[0];
        let model = &matrix.models[0];
        let task = clean_task();

        let cell = unavailable_harness_model_cell(
            harness,
            model,
            &task,
            EvalExecutionMode::LiveHarness,
            "transcripts/unavailable.txt".to_string(),
            "missing provider budget acknowledgement".to_string(),
        );

        assert_eq!(cell.execution_mode, EvalExecutionMode::LiveHarness);
        assert_eq!(cell.status, EvalCellStatus::Unavailable);
        assert_eq!(
            cell.failure_reason.as_deref(),
            Some("missing provider budget acknowledgement")
        );
    }

    #[test]
    fn harness_model_readiness_blocks_provider_cells_without_env_or_budget_ack() {
        let suite = suite();
        let matrix = matrix();
        let profiles = provider_profiles(true);
        let probes = vec![HarnessProbe {
            harness_id: "pi".to_string(),
            available: true,
            version: Some("0.78.1".to_string()),
            path: Some("/bin/pi".to_string()),
            failure_reason: None,
        }];
        let peer_runner_probes = vec![HarnessProbe {
            harness_id: "pi".to_string(),
            available: true,
            version: None,
            path: Some("/bin/cerberus-peer-harness".to_string()),
            failure_reason: None,
        }];
        let available_env = BTreeSet::new();

        let report = harness_model_readiness_report(
            &suite,
            &matrix,
            &probes,
            &peer_runner_probes,
            &profiles,
            &available_env,
            false,
        )
        .expect("readiness report builds");

        report.validate().expect("readiness report validates");
        assert_eq!(report.summary.total_cells, 2);
        assert_eq!(report.summary.runnable_cells, 0);
        assert_eq!(report.summary.unavailable_peer_runner_cells, 0);
        assert_eq!(report.summary.missing_env_cells, 2);
        assert_eq!(report.summary.budget_blocked_cells, 2);
        assert!(report.cells.iter().all(|cell| {
            !cell.runnable
                && cell.env_missing == vec!["OPENROUTER_API_KEY".to_string()]
                && cell
                    .blockers
                    .iter()
                    .any(|blocker| blocker.contains("provider budget"))
        }));
    }

    #[test]
    fn harness_model_readiness_reports_runnable_cells_when_env_and_budget_are_present() {
        let suite = suite();
        let matrix = matrix();
        let profiles = provider_profiles(true);
        let probes = vec![HarnessProbe {
            harness_id: "pi".to_string(),
            available: true,
            version: Some("0.78.1".to_string()),
            path: Some("/bin/pi".to_string()),
            failure_reason: None,
        }];
        let peer_runner_probes = vec![HarnessProbe {
            harness_id: "pi".to_string(),
            available: true,
            version: None,
            path: Some("/bin/cerberus-peer-harness".to_string()),
            failure_reason: None,
        }];
        let available_env = BTreeSet::from(["OPENROUTER_API_KEY".to_string()]);

        let report = harness_model_readiness_report(
            &suite,
            &matrix,
            &probes,
            &peer_runner_probes,
            &profiles,
            &available_env,
            true,
        )
        .expect("readiness report builds");

        assert_eq!(report.summary.total_cells, 2);
        assert_eq!(report.summary.runnable_cells, 2);
        assert_eq!(report.summary.missing_env_cells, 0);
        assert_eq!(report.summary.budget_blocked_cells, 0);
        assert!(report
            .cells
            .iter()
            .all(|cell| cell.runnable && cell.peer_runner_available && cell.blockers.is_empty()));
    }

    #[test]
    fn harness_model_readiness_blocks_cells_when_peer_runner_is_unavailable() {
        let suite = suite();
        let matrix = matrix();
        let profiles = provider_profiles(true);
        let probes = vec![HarnessProbe {
            harness_id: "pi".to_string(),
            available: true,
            version: Some("0.78.1".to_string()),
            path: Some("/bin/pi".to_string()),
            failure_reason: None,
        }];
        let peer_runner_probes = vec![HarnessProbe {
            harness_id: "pi".to_string(),
            available: false,
            version: None,
            path: None,
            failure_reason: Some("cerberus-peer-harness unavailable".to_string()),
        }];
        let available_env = BTreeSet::from(["OPENROUTER_API_KEY".to_string()]);

        let report = harness_model_readiness_report(
            &suite,
            &matrix,
            &probes,
            &peer_runner_probes,
            &profiles,
            &available_env,
            true,
        )
        .expect("readiness report builds");

        report.validate().expect("readiness report validates");
        assert_eq!(report.summary.total_cells, 2);
        assert_eq!(report.summary.runnable_cells, 0);
        assert_eq!(report.summary.unavailable_peer_runner_cells, 2);
        assert_eq!(report.summary.missing_env_cells, 0);
        assert_eq!(report.summary.budget_blocked_cells, 0);
        assert!(report.cells.iter().all(|cell| {
            !cell.runnable
                && !cell.peer_runner_available
                && cell
                    .blockers
                    .iter()
                    .any(|blocker| blocker.contains("peer harness runner unavailable"))
        }));
    }

    #[test]
    fn reviewer_config_candidate_from_live_eval_report_builds_sandbox_packet() {
        let matrix = matrix();
        let harness = &matrix.harnesses[0];
        let model = &matrix.models[0];
        let task = clean_task();
        let reviewer = eval_reviewer_config(harness, model, &task);
        let config = ReviewConfig {
            schema_version: REVIEW_CONFIG_VERSION.to_string(),
            config_id: "live-candidate-source".to_string(),
            reviewers: vec![reviewer],
            confidence_min: 0.7,
        };
        let artifact = crate::review(&task.review_request, &config)
            .expect("fixture review succeeds")
            .reviewer_artifacts
            .into_iter()
            .next()
            .expect("one artifact");
        let cell = evaluate_harness_model_artifact(
            harness,
            model,
            &task,
            EvalExecutionMode::LiveHarness,
            artifact,
            100,
            "transcripts/live.txt".to_string(),
        )
        .expect("live cell evaluates");
        let suite = EvalTaskSuite {
            schema_version: EVAL_TASK_SUITE_VERSION.to_string(),
            suite_id: "candidate-suite".to_string(),
            description: None,
            tasks: vec![task],
        };
        let output = harness_model_evaluation_output(&suite, &matrix, vec![cell], vec![], vec![])
            .expect("report builds");
        let transcripts = live_transcripts(&output.report.cells);

        let packet = reviewer_config_candidate_from_eval_report(
            &output.report,
            &matrix,
            &suite,
            &transcripts,
        )
        .expect("candidate packet builds");
        let digest =
            crate::validate_reviewer_config_packet(&packet).expect("packet validates in core");
        let dry_run = crate::reviewer_config_import_dry_run(
            &packet,
            &crate::default_config(),
            &crate::reviewer_config_promotion_fixture_request(),
        )
        .expect("candidate imports as dry run");

        assert_eq!(packet.producer.system, "cerberus-eval-harness");
        assert!(packet.producer.sandbox_only);
        assert_eq!(packet.promotion.status, PromotionStatus::Candidate);
        assert_eq!(packet.config.reviewers.len(), 3);
        assert!(packet
            .config
            .reviewers
            .iter()
            .all(|reviewer| reviewer.model == "fake:fake/model"));
        assert_eq!(packet.config_hash, digest);
        assert!(dry_run.accepted_for_dry_run);
        assert!(!dry_run.accepted_for_import);
        assert!(dry_run
            .rejection_reasons
            .iter()
            .any(|reason| reason.contains("sandbox-only")));
    }

    #[test]
    fn reviewer_config_candidate_refuses_offline_eval_report() {
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

        let transcripts = output.transcripts.into_iter().collect::<BTreeMap<_, _>>();
        let error = reviewer_config_candidate_from_eval_report(
            &output.report,
            &matrix,
            &suite,
            &transcripts,
        )
        .expect_err("offline warn cells cannot produce candidates");

        assert!(error.to_string().contains("no fully passing live_harness"));
    }

    #[test]
    fn reviewer_config_candidate_refuses_cherry_picked_report_without_suite_coverage() {
        let matrix = matrix();
        let harness = &matrix.harnesses[0];
        let model = &matrix.models[0];
        let task = clean_task();
        let reviewer = eval_reviewer_config(harness, model, &task);
        let config = ReviewConfig {
            schema_version: REVIEW_CONFIG_VERSION.to_string(),
            config_id: "cherry-picked-source".to_string(),
            reviewers: vec![reviewer],
            confidence_min: 0.7,
        };
        let artifact = crate::review(&task.review_request, &config)
            .expect("fixture review succeeds")
            .reviewer_artifacts
            .into_iter()
            .next()
            .expect("one artifact");
        let cell = evaluate_harness_model_artifact(
            harness,
            model,
            &task,
            EvalExecutionMode::LiveHarness,
            artifact,
            100,
            "transcripts/live.txt".to_string(),
        )
        .expect("live cell evaluates");
        let suite = suite();
        let truncated_suite = EvalTaskSuite {
            schema_version: EVAL_TASK_SUITE_VERSION.to_string(),
            suite_id: suite.suite_id.clone(),
            description: None,
            tasks: vec![task],
        };
        let output =
            harness_model_evaluation_output(&truncated_suite, &matrix, vec![cell], vec![], vec![])
                .expect("report builds");
        let transcripts = live_transcripts(&output.report.cells);

        let error = reviewer_config_candidate_from_eval_report(
            &output.report,
            &matrix,
            &suite,
            &transcripts,
        )
        .expect_err("candidate requires full suite coverage");

        assert!(error.to_string().contains("no fully passing live_harness"));
    }

    #[test]
    fn reviewer_config_candidate_regrades_report_artifacts_before_accepting_pass() {
        let matrix = matrix();
        let harness = &matrix.harnesses[0];
        let model = &matrix.models[0];
        let task = seeded_task();
        let reviewer = eval_reviewer_config(harness, model, &task);
        let config = ReviewConfig {
            schema_version: REVIEW_CONFIG_VERSION.to_string(),
            config_id: "tampered-live-source".to_string(),
            reviewers: vec![reviewer],
            confidence_min: 0.7,
        };
        let artifact = crate::review(&task.review_request, &config)
            .expect("fixture review succeeds")
            .reviewer_artifacts
            .into_iter()
            .next()
            .expect("one artifact");
        let mut cell = evaluate_harness_model_artifact(
            harness,
            model,
            &task,
            EvalExecutionMode::LiveHarness,
            artifact,
            100,
            "transcripts/live.txt".to_string(),
        )
        .expect("live cell evaluates");
        assert_eq!(cell.status, EvalCellStatus::Pass);
        cell.reviewer_artifact
            .as_mut()
            .expect("passing cell has artifact")
            .findings
            .clear();
        let suite = EvalTaskSuite {
            schema_version: EVAL_TASK_SUITE_VERSION.to_string(),
            suite_id: "tampered-suite".to_string(),
            description: None,
            tasks: vec![task],
        };
        let output = harness_model_evaluation_output(&suite, &matrix, vec![cell], vec![], vec![])
            .expect("report builds");
        let transcripts = live_transcripts(&output.report.cells);

        let error = reviewer_config_candidate_from_eval_report(
            &output.report,
            &matrix,
            &suite,
            &transcripts,
        )
        .expect_err("candidate regrades embedded artifacts before accepting pass");

        assert!(error.to_string().contains("regraded as Fail"));
    }

    #[test]
    fn reviewer_config_candidate_refuses_offline_report_edited_to_live_pass() {
        let suite = suite();
        let matrix = matrix();
        let probes = vec![HarnessProbe {
            harness_id: "pi".to_string(),
            available: true,
            version: Some("0.78.1".to_string()),
            path: Some("/bin/pi".to_string()),
            failure_reason: None,
        }];
        let mut output =
            evaluate_harness_model_matrix(&suite, &matrix, &probes, vec![]).expect("eval passes");
        let transcripts = output
            .transcripts
            .iter()
            .cloned()
            .collect::<BTreeMap<_, _>>();
        for cell in &mut output.report.cells {
            assert_eq!(cell.execution_mode, EvalExecutionMode::OfflineContract);
            assert_eq!(cell.status, EvalCellStatus::Warn);
            cell.execution_mode = EvalExecutionMode::LiveHarness;
            cell.status = EvalCellStatus::Pass;
        }
        output.report.summary = summarize_cells(&output.report.cells);

        let error = reviewer_config_candidate_from_eval_report(
            &output.report,
            &matrix,
            &suite,
            &transcripts,
        )
        .expect_err("offline transcripts cannot be promoted by editing cell mode");

        assert!(error
            .to_string()
            .contains("live transcript must contain exactly one"));
    }

    fn live_transcripts(cells: &[HarnessModelEvaluationCell]) -> BTreeMap<String, String> {
        cells
            .iter()
            .map(|cell| {
                (
                    cell.transcript_path.clone(),
                    live_transcript_for_cell(cell).expect("live transcript builds"),
                )
            })
            .collect()
    }

    fn live_transcript_for_cell(cell: &HarnessModelEvaluationCell) -> Result<String, CoreError> {
        let artifact = cell.reviewer_artifact.as_ref().ok_or_else(|| {
            CoreError::EvalReportCandidate(format!(
                "cell {:?} has no reviewer artifact",
                cell.cell_id
            ))
        })?;
        let json = serde_json::to_string_pretty(artifact)?;
        Ok(format!(
            "fixture live transcript\n{LIVE_TRANSCRIPT_ARTIFACT_BEGIN_MARKER}\n{json}\n{LIVE_TRANSCRIPT_ARTIFACT_END_MARKER}\n"
        ))
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

    fn provider_profiles(
        requires_provider_budget_ack: bool,
    ) -> cerberus_schema::PeerHarnessCommandProfiles {
        cerberus_schema::PeerHarnessCommandProfiles {
            schema_version: cerberus_schema::PEER_HARNESS_COMMAND_PROFILES_VERSION.to_string(),
            observed_at: "2026-06-19".to_string(),
            profiles: vec![cerberus_schema::PeerHarnessCommandProfile {
                harness_id: "pi".to_string(),
                command: "cerberus-peer-harness".to_string(),
                args: vec!["--harness".to_string(), "pi".to_string()],
                timeout_ms: 300_000,
                env_required: vec!["OPENROUTER_API_KEY".to_string()],
                requires_provider_budget_ack,
                output_contract: cerberus_schema::PeerHarnessOutputContract::ReviewerArtifactFile,
                peer: cerberus_schema::PeerHarnessInvocation {
                    command: "pi".to_string(),
                    args_template: vec![
                        "--print".to_string(),
                        "--model".to_string(),
                        "openrouter/{model}".to_string(),
                        "@{prompt_file}".to_string(),
                    ],
                    prompt_mode: cerberus_schema::PeerHarnessPromptMode::PromptFile,
                    notes: None,
                },
                unsupported: vec!["paid provider calls without budget ack".to_string()],
                notes: None,
            }],
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
