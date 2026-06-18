use crate::{validate_artifact_for_request, AdapterError};
use cerberus_schema::{
    Caller, Change, ChangedFile, CostSummary, Coverage, FakeReviewerBehavior, FileStatus,
    RenderTarget, ReserveSignal, ReviewConfig, ReviewContext, ReviewPolicy, ReviewRequest,
    ReviewRunArtifact, ReviewSource, ReviewerArtifact, ReviewerConfig, ReviewerStatus, TokenUsage,
    Verdict, VerdictStats, REVIEWER_ARTIFACT_VERSION, REVIEW_CONFIG_VERSION,
    REVIEW_REQUEST_VERSION, REVIEW_RUN_ARTIFACT_VERSION,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};

pub const THINKTANK_HISTORICAL_RUN_VERSION: &str = "thinktank-historical-run.v1";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ThinkTankHistoricalRun {
    pub fixture_version: String,
    pub run_id: String,
    pub bench: String,
    pub version: String,
    pub status: String,
    pub started_at: String,
    pub completed_at: String,
    pub workspace_root: String,
    pub task: String,
    pub git: ThinkTankGit,
    pub change: ThinkTankChange,
    pub plan: ThinkTankPlan,
    pub agents: Vec<ThinkTankAgent>,
    #[serde(default)]
    pub missing_artifacts: Vec<String>,
}

impl ThinkTankHistoricalRun {
    pub fn validate(&self) -> Result<(), AdapterError> {
        if self.fixture_version != THINKTANK_HISTORICAL_RUN_VERSION {
            return Err(AdapterError::UnsupportedThinkTankFixtureVersion {
                actual: self.fixture_version.clone(),
            });
        }
        if self.agents.is_empty() {
            return Err(AdapterError::MissingThinkTankAgents);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ThinkTankGit {
    pub base: String,
    pub branch: String,
    pub head: String,
    pub head_sha: String,
    pub merge_base: String,
    pub range: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ThinkTankChange {
    pub title: String,
    pub summary: String,
    pub diff_summary: String,
    pub added: u64,
    pub deleted: u64,
    pub directories: Vec<String>,
    pub files: Vec<ThinkTankChangedFile>,
    pub signals: BTreeMap<String, bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ThinkTankChangedFile {
    pub path: String,
    pub status: FileStatus,
    #[serde(default)]
    pub additions: u64,
    #[serde(default)]
    pub deletions: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ThinkTankPlan {
    pub source: String,
    pub summary: String,
    pub synthesis_brief: String,
    pub selected_agents: Vec<ThinkTankPlanAgent>,
    #[serde(default)]
    pub warnings: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ThinkTankPlanAgent {
    pub name: String,
    pub perspective: String,
    pub brief: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ThinkTankAgent {
    pub name: String,
    pub instance_id: String,
    pub file: String,
    pub provider: String,
    pub model: String,
    pub status: String,
    pub duration_ms: u64,
    #[serde(default)]
    pub error_category: Option<String>,
    pub verdict: Verdict,
    pub summary: String,
    #[serde(default)]
    pub reviewed_files: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ThinkTankMigrationOutput {
    pub request: ReviewRequest,
    pub config: ReviewConfig,
    pub artifact: ReviewRunArtifact,
}

pub fn import_thinktank_historical_run(
    run: &ThinkTankHistoricalRun,
) -> Result<ThinkTankMigrationOutput, AdapterError> {
    run.validate()?;
    let request = review_request(run)?;
    let config = review_config(run)?;
    let reviewer_artifacts = run
        .agents
        .iter()
        .map(|agent| reviewer_artifact(run, agent))
        .collect::<Result<Vec<_>, _>>()?;
    let stats = verdict_stats(&reviewer_artifacts);
    let pre_override_verdict = aggregate_verdict(&reviewer_artifacts, &stats);
    let artifact = ReviewRunArtifact {
        schema_version: REVIEW_RUN_ARTIFACT_VERSION.to_string(),
        run_id: run.run_id.clone(),
        request_id: request.request_id.clone(),
        request_digest: digest_json(&request)?,
        config_digest: digest_json(&config)?,
        reviewed_head_sha: request.change.head_sha.clone(),
        pre_override_verdict,
        verdict: pre_override_verdict,
        summary: artifact_summary(run, &reviewer_artifacts),
        findings: vec![],
        reviewer_artifacts,
        stats,
        coverage: aggregate_coverage(&run.agents),
        degraded: run.status == "degraded",
        reserves: reserve_signals(&run.agents),
        override_applied: None,
        cost: aggregate_cost(&run.agents),
    };

    artifact.validate()?;
    validate_artifact_for_request(&request, &artifact)?;
    Ok(ThinkTankMigrationOutput {
        request,
        config,
        artifact,
    })
}

fn review_request(run: &ThinkTankHistoricalRun) -> Result<ReviewRequest, AdapterError> {
    let mut metadata = BTreeMap::new();
    metadata.insert("bench".to_string(), run.bench.clone());
    metadata.insert("historical_status".to_string(), run.status.clone());
    metadata.insert("plan_source".to_string(), run.plan.source.clone());
    metadata.insert("thinktank_version".to_string(), run.version.clone());
    metadata.insert("git_merge_base".to_string(), run.git.merge_base.clone());
    metadata.insert("git_range".to_string(), run.git.range.clone());
    metadata.insert("line_stats_added".to_string(), run.change.added.to_string());
    metadata.insert(
        "line_stats_deleted".to_string(),
        run.change.deleted.to_string(),
    );
    metadata.insert(
        "missing_artifacts".to_string(),
        run.missing_artifacts.join(","),
    );
    metadata.insert("planned_agents".to_string(), planned_agents(run).join(","));
    metadata.insert("started_at".to_string(), run.started_at.clone());
    metadata.insert("completed_at".to_string(), run.completed_at.clone());
    metadata.insert("workspace_root".to_string(), run.workspace_root.clone());
    metadata.insert("plan_summary".to_string(), run.plan.summary.clone());
    metadata.insert(
        "synthesis_brief".to_string(),
        run.plan.synthesis_brief.clone(),
    );
    for (signal, enabled) in &run.change.signals {
        metadata.insert(format!("signal_{signal}"), enabled.to_string());
    }

    let request = ReviewRequest {
        schema_version: REVIEW_REQUEST_VERSION.to_string(),
        request_id: run.run_id.clone(),
        source: ReviewSource::External {
            system: "thinktank-historical-run".to_string(),
            id: run.run_id.clone(),
        },
        change: Change {
            title: run.change.title.clone(),
            description: Some(run.change.summary.clone()),
            base_ref: Some(run.git.base.clone()),
            head_ref: Some(run.git.branch.clone()),
            head_sha: Some(run.git.head_sha.clone()),
            diff: run.change.diff_summary.clone(),
            files: run
                .change
                .files
                .iter()
                .map(|file| ChangedFile {
                    path: file.path.clone(),
                    status: file.status,
                    additions: file.additions,
                    deletions: file.deletions,
                })
                .collect(),
        },
        context: ReviewContext {
            summary: Some(run.task.clone()),
            acceptance: vec![
                "Historical replay must not invoke the ThinkTank CLI.".to_string(),
                "Missing historical coverage/degrade artifacts stay explicit in metadata."
                    .to_string(),
            ],
            linked_artifacts: vec![
                format!("thinktank://{}/manifest.json", run.run_id),
                format!("thinktank://{}/review/context.json", run.run_id),
                format!("thinktank://{}/review/plan.json", run.run_id),
            ],
            metadata,
        },
        caller: Caller {
            name: "thinktank-migration".to_string(),
            run_id: run.run_id.clone(),
        },
        policy: ReviewPolicy {
            render_targets: vec![RenderTarget::Json],
            allow_degraded: true,
            max_cost_usd: None,
            override_approval: None,
        },
    };
    request.validate()?;
    Ok(request)
}

fn review_config(run: &ThinkTankHistoricalRun) -> Result<ReviewConfig, AdapterError> {
    let config = ReviewConfig {
        schema_version: REVIEW_CONFIG_VERSION.to_string(),
        config_id: format!("{}-config", run.run_id),
        reviewers: run
            .agents
            .iter()
            .map(|agent| ReviewerConfig {
                id: agent.name.clone(),
                perspective: plan_perspective(run, &agent.name),
                model: model_with_provider(agent),
                fake_behavior: if agent.status == "ok" {
                    FakeReviewerBehavior::Pass
                } else {
                    FakeReviewerBehavior::Degraded
                },
            })
            .collect(),
        confidence_min: 0.7,
    };
    config.validate()?;
    Ok(config)
}

fn reviewer_artifact(
    run: &ThinkTankHistoricalRun,
    agent: &ThinkTankAgent,
) -> Result<ReviewerArtifact, AdapterError> {
    let status = match (agent.status.as_str(), agent.error_category.as_deref()) {
        ("ok", _) => ReviewerStatus::Completed,
        ("error", Some("timeout")) => ReviewerStatus::Timeout,
        ("error", _) => ReviewerStatus::Error,
        ("degraded", _) => ReviewerStatus::Degraded,
        _ => {
            return Err(AdapterError::UnsupportedThinkTankAgentStatus {
                agent: agent.name.clone(),
                status: agent.status.clone(),
            })
        }
    };

    let artifact = ReviewerArtifact {
        schema_version: REVIEWER_ARTIFACT_VERSION.to_string(),
        reviewer_id: agent.name.clone(),
        perspective: plan_perspective(run, &agent.name),
        model: model_with_provider(agent),
        status,
        verdict: agent.verdict,
        summary: agent.summary.clone(),
        findings: vec![],
        coverage: Coverage {
            files_reviewed: sorted(agent.reviewed_files.clone()),
            files_with_findings: vec![],
        },
        usage: TokenUsage {
            prompt_tokens: 0,
            completion_tokens: 0,
        },
        cost_usd: 0.0,
        degraded_reason: if status == ReviewerStatus::Completed {
            None
        } else {
            Some(
                agent
                    .error_category
                    .clone()
                    .unwrap_or_else(|| "historical reviewer did not complete".to_string()),
            )
        },
    };
    artifact.validate()?;
    Ok(artifact)
}

fn artifact_summary(run: &ThinkTankHistoricalRun, agents: &[ReviewerArtifact]) -> String {
    let completed = agents
        .iter()
        .filter(|agent| agent.status == ReviewerStatus::Completed)
        .count();
    let degraded = agents.len() - completed;
    format!(
        "Migrated historical ThinkTank {bench} run with {completed} completed reviewer(s), {degraded} degraded reviewer(s), and no migrated findings.",
        bench = run.bench
    )
}

fn planned_agents(run: &ThinkTankHistoricalRun) -> Vec<String> {
    run.plan
        .selected_agents
        .iter()
        .map(|agent| agent.name.clone())
        .collect()
}

fn plan_perspective(run: &ThinkTankHistoricalRun, name: &str) -> String {
    run.plan
        .selected_agents
        .iter()
        .find(|agent| agent.name == name)
        .map(|agent| agent.perspective.clone())
        .unwrap_or_else(|| name.to_string())
}

fn model_with_provider(agent: &ThinkTankAgent) -> String {
    format!("{}:{}", agent.provider, agent.model)
}

fn sorted(values: Vec<String>) -> Vec<String> {
    values
        .into_iter()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}

fn verdict_stats(artifacts: &[ReviewerArtifact]) -> VerdictStats {
    let mut stats = VerdictStats {
        total: artifacts.len() as u64,
        pass: 0,
        warn: 0,
        fail: 0,
        skip: 0,
    };
    for artifact in artifacts {
        match artifact.verdict {
            Verdict::Pass => stats.pass += 1,
            Verdict::Warn => stats.warn += 1,
            Verdict::Fail => stats.fail += 1,
            Verdict::Skip => stats.skip += 1,
        }
    }
    stats
}

fn aggregate_verdict(artifacts: &[ReviewerArtifact], stats: &VerdictStats) -> Verdict {
    if stats.total > 0 && stats.skip == stats.total {
        return Verdict::Skip;
    }
    if artifacts
        .iter()
        .any(|artifact| artifact.verdict == Verdict::Fail)
    {
        Verdict::Fail
    } else if artifacts
        .iter()
        .any(|artifact| artifact.verdict == Verdict::Warn)
    {
        Verdict::Warn
    } else {
        Verdict::Pass
    }
}

fn aggregate_coverage(agents: &[ThinkTankAgent]) -> Coverage {
    Coverage {
        files_reviewed: agents
            .iter()
            .flat_map(|agent| agent.reviewed_files.clone())
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect(),
        files_with_findings: vec![],
    }
}

fn reserve_signals(agents: &[ThinkTankAgent]) -> Vec<ReserveSignal> {
    if agents.iter().any(|agent| agent.status != "ok") {
        vec![ReserveSignal::DegradedReviewer]
    } else {
        vec![]
    }
}

fn aggregate_cost(agents: &[ThinkTankAgent]) -> CostSummary {
    CostSummary {
        total_usd: 0.0,
        per_reviewer: agents
            .iter()
            .map(|agent| (agent.name.clone(), 0.0))
            .collect::<BTreeMap<_, _>>(),
    }
}

fn digest_json<T: Serialize>(value: &T) -> Result<String, AdapterError> {
    let bytes = serde_json::to_vec(value)?;
    let digest = Sha256::digest(bytes);
    Ok(format!("{digest:x}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    const HISTORICAL_RUN: &str =
        include_str!("../../../fixtures/thinktank/review-pr-289/historical-run.json");
    const CONVERTED_ARTIFACT: &str =
        include_str!("../../../fixtures/thinktank/review-pr-289/review-run-artifact.json");

    #[test]
    fn thinktank_migration_imports_frozen_review_run_as_valid_artifact() {
        let run: ThinkTankHistoricalRun =
            serde_json::from_str(HISTORICAL_RUN).expect("historical fixture parses");
        let output =
            import_thinktank_historical_run(&run).expect("historical fixture imports cleanly");
        let expected: ReviewRunArtifact =
            serde_json::from_str(CONVERTED_ARTIFACT).expect("converted fixture parses");

        output.request.validate().expect("request validates");
        output.config.validate().expect("config validates");
        output.artifact.validate().expect("artifact validates");
        expected.validate().expect("checked artifact validates");
        validate_artifact_for_request(&output.request, &output.artifact)
            .expect("imported artifact belongs to imported request");

        assert_eq!(output.artifact, expected);
        assert_eq!(output.artifact.stats.pass, 2);
        assert_eq!(output.artifact.stats.skip, 1);
        assert_eq!(
            output.artifact.reserves,
            vec![ReserveSignal::DegradedReviewer]
        );
    }

    #[test]
    fn thinktank_migration_no_runtime_dependency_guard_scopes_references() {
        let crate_root = Path::new(env!("CARGO_MANIFEST_DIR"));
        let repo_root = crate_root
            .parent()
            .and_then(Path::parent)
            .expect("adapter crate lives under crates/");
        let crates_root = repo_root.join("crates");
        let allowed = [
            "crates/cerberus-adapter/src/lib.rs",
            "crates/cerberus-adapter/src/thinktank_migration.rs",
        ];
        let mut offenders = Vec::new();
        scan_for_term(&crates_root, repo_root, &allowed, &mut offenders);
        assert_importer_does_not_spawn_process(repo_root);

        assert!(
            offenders.is_empty(),
            "unexpected ThinkTank runtime references: {offenders:?}"
        );
    }

    fn scan_for_term(path: &Path, repo_root: &Path, allowed: &[&str], offenders: &mut Vec<String>) {
        if path.is_dir() {
            for entry in std::fs::read_dir(path).expect("scan directory") {
                let entry = entry.expect("directory entry");
                scan_for_term(&entry.path(), repo_root, allowed, offenders);
            }
            return;
        }

        if path.extension().and_then(|ext| ext.to_str()) != Some("rs") {
            return;
        }

        let text = std::fs::read_to_string(path).expect("read source file");
        if !text.to_lowercase().contains("thinktank") {
            return;
        }

        let relative = path
            .strip_prefix(repo_root)
            .expect("path is in repo")
            .to_string_lossy()
            .to_string();
        if !allowed.contains(&relative.as_str()) {
            offenders.push(relative);
        }
    }

    fn assert_importer_does_not_spawn_process(repo_root: &Path) {
        let importer_path = repo_root
            .join("crates")
            .join("cerberus-adapter")
            .join("src")
            .join("thinktank_migration.rs");
        let text = std::fs::read_to_string(importer_path).expect("read importer");
        let production_text = text
            .split("\n#[cfg(test)]")
            .next()
            .expect("module has production section");
        for forbidden in [
            "std::process",
            "process::Command",
            "Command::new",
            "tokio::process",
            "duct::",
            "xshell",
        ] {
            assert!(
                !production_text.contains(forbidden),
                "ThinkTank migration importer must not spawn processes through {forbidden:?}"
            );
        }
    }
}
