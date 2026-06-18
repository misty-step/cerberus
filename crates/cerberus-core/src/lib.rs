use cerberus_schema::{
    ChangedFile, CostSummary, Coverage, FakeReviewerBehavior, Finding, InlineCommentCandidate,
    ReserveSignal, ReviewConfig, ReviewRequest, ReviewRunArtifact, ReviewerArtifact,
    ReviewerConfig, ReviewerStatus, Severity, TokenUsage, Verdict, VerdictStats,
    INLINE_COMMENT_CANDIDATE_VERSION, REVIEWER_ARTIFACT_VERSION, REVIEW_CONFIG_VERSION,
    REVIEW_RUN_ARTIFACT_VERSION,
};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};

mod harness_eval;
pub use harness_eval::*;

#[derive(Debug, thiserror::Error)]
pub enum CoreError {
    #[error(transparent)]
    Schema(#[from] cerberus_schema::SchemaError),
    #[error("serialization failed: {0}")]
    Serialization(#[from] serde_json::Error),
}

pub fn default_config() -> ReviewConfig {
    ReviewConfig {
        schema_version: REVIEW_CONFIG_VERSION.to_string(),
        config_id: "default-fake-review-panel".to_string(),
        reviewers: vec![
            reviewer("correctness", "correctness"),
            reviewer("security", "security"),
            reviewer("testing", "testing"),
        ],
        confidence_min: 0.7,
    }
}

pub fn review(
    request: &ReviewRequest,
    config: &ReviewConfig,
) -> Result<ReviewRunArtifact, CoreError> {
    request.validate()?;
    config.validate()?;

    let request_digest = digest_json(request)?;
    let config_digest = digest_json(config)?;
    let reviewer_artifacts = config
        .reviewers
        .iter()
        .map(|reviewer| fake_review(reviewer, request))
        .collect::<Vec<_>>();
    let findings = dedupe_findings(
        reviewer_artifacts
            .iter()
            .flat_map(|artifact| artifact.findings.clone())
            .collect(),
    );
    let stats = verdict_stats(&reviewer_artifacts);
    let pre_override_verdict = aggregate_verdict(&reviewer_artifacts, &stats);
    let mut verdict = pre_override_verdict;
    let override_applied = request
        .policy
        .override_approval
        .clone()
        .filter(|_| matches!(verdict, Verdict::Fail | Verdict::Warn));
    if override_applied.is_some() {
        verdict = Verdict::Pass;
    }
    let coverage = aggregate_coverage(&request.change.files, &reviewer_artifacts);
    let cost = aggregate_cost(&reviewer_artifacts);
    let degraded = reviewer_artifacts
        .iter()
        .any(|artifact| artifact.status != ReviewerStatus::Completed);
    let reserves = reserve_signals(&reviewer_artifacts);
    let summary = summarize(
        verdict,
        &reviewer_artifacts,
        findings.len(),
        override_applied.as_ref(),
    );

    let artifact = ReviewRunArtifact {
        schema_version: REVIEW_RUN_ARTIFACT_VERSION.to_string(),
        run_id: format!("review-run-{}", &request_digest[..12]),
        request_id: request.request_id.clone(),
        request_digest,
        config_digest,
        reviewed_head_sha: request.change.head_sha.clone(),
        pre_override_verdict,
        verdict,
        summary,
        findings,
        reviewer_artifacts,
        stats,
        coverage,
        degraded,
        reserves,
        override_applied,
        cost,
    };

    artifact.validate()?;
    Ok(artifact)
}

pub fn render_markdown(artifact: &ReviewRunArtifact) -> String {
    let mut out = String::new();
    out.push_str("# Cerberus Review\n\n");
    out.push_str(&format!("Verdict: **{}**\n\n", artifact.verdict.as_str()));
    out.push_str(&format!("{}\n\n", artifact.summary));
    out.push_str("## Reviewer Artifacts\n\n");
    for reviewer in &artifact.reviewer_artifacts {
        out.push_str(&format!(
            "- `{}` ({}) -> {}",
            reviewer.reviewer_id,
            reviewer.perspective,
            reviewer.verdict.as_str()
        ));
        if let Some(reason) = &reviewer.degraded_reason {
            out.push_str(&format!(" ({reason})"));
        }
        out.push('\n');
    }

    if artifact.findings.is_empty() {
        out.push_str("\n## Findings\n\nNo findings.\n");
    } else {
        out.push_str("\n## Findings\n\n");
        for finding in &artifact.findings {
            out.push_str(&format!(
                "- **{}** `{}`: {} ({}:{})\n",
                finding.severity.as_str(),
                finding.category,
                finding.title,
                finding.citation.path,
                finding.citation.line.unwrap_or(0)
            ));
        }
    }

    out
}

pub fn render_inline_comment_candidates(
    artifact: &ReviewRunArtifact,
) -> Vec<InlineCommentCandidate> {
    artifact
        .findings
        .iter()
        .map(|finding| InlineCommentCandidate {
            schema_version: INLINE_COMMENT_CANDIDATE_VERSION.to_string(),
            finding_id: finding.id.clone(),
            reviewer_id: finding.reviewer_id.clone(),
            perspective: finding.perspective.clone(),
            path: finding.citation.path.clone(),
            line: finding.citation.line.unwrap_or(1),
            severity: finding.severity,
            body: inline_comment_body(finding),
        })
        .collect()
}

fn reviewer(id: &str, perspective: &str) -> ReviewerConfig {
    ReviewerConfig {
        id: id.to_string(),
        perspective: perspective.to_string(),
        model: "fake/offline-reviewer".to_string(),
        fake_behavior: FakeReviewerBehavior::Directive,
    }
}

fn inline_comment_body(finding: &Finding) -> String {
    format!(
        "**{}** `{}`: {}\n\n{}\n\nEvidence: `{}`",
        finding.severity.as_str(),
        finding.category,
        finding.title,
        finding.description,
        finding.evidence
    )
}

fn fake_review(reviewer: &ReviewerConfig, request: &ReviewRequest) -> ReviewerArtifact {
    if reviewer.fake_behavior == FakeReviewerBehavior::Degraded
        || request
            .context
            .metadata
            .get("fake_degraded")
            .is_some_and(|value| value == "true")
    {
        return ReviewerArtifact {
            schema_version: REVIEWER_ARTIFACT_VERSION.to_string(),
            reviewer_id: reviewer.id.clone(),
            perspective: reviewer.perspective.clone(),
            model: reviewer.model.clone(),
            status: ReviewerStatus::Timeout,
            verdict: Verdict::Skip,
            summary: "Reviewer did not complete in the fake harness.".to_string(),
            findings: vec![],
            coverage: coverage_for_request(&request.change.files, vec![]),
            usage: TokenUsage {
                prompt_tokens: 0,
                completion_tokens: 0,
            },
            cost_usd: 0.0,
            degraded_reason: Some("fixture requested degraded reviewer".to_string()),
        };
    }

    let findings = match reviewer.fake_behavior {
        FakeReviewerBehavior::Pass => vec![],
        FakeReviewerBehavior::Directive | FakeReviewerBehavior::Degraded => {
            directive_findings(reviewer, request)
        }
    };
    let verdict = if findings
        .iter()
        .any(|finding| finding.severity >= Severity::Major)
    {
        Verdict::Fail
    } else if findings.is_empty() {
        Verdict::Pass
    } else {
        Verdict::Warn
    };
    let files_with_findings = findings
        .iter()
        .map(|finding| finding.citation.path.clone())
        .collect::<Vec<_>>();

    ReviewerArtifact {
        schema_version: REVIEWER_ARTIFACT_VERSION.to_string(),
        reviewer_id: reviewer.id.clone(),
        perspective: reviewer.perspective.clone(),
        model: reviewer.model.clone(),
        status: ReviewerStatus::Completed,
        verdict,
        summary: if findings.is_empty() {
            "No issues found by fake reviewer.".to_string()
        } else {
            format!("{} fixture finding(s) emitted.", findings.len())
        },
        findings,
        coverage: coverage_for_request(&request.change.files, files_with_findings),
        usage: fake_usage(request),
        cost_usd: 0.0,
        degraded_reason: None,
    }
}

fn directive_findings(reviewer: &ReviewerConfig, request: &ReviewRequest) -> Vec<Finding> {
    // The fake harness only reacts to exact fixture directives. It is not a
    // semantic classifier; live LLM review belongs to a later backlog item.
    if !request.change.diff.contains("CERBERUS_FAKE_FINDING") {
        return vec![];
    }

    let first_file = request
        .change
        .files
        .first()
        .expect("validated request has at least one file");

    vec![Finding {
        id: format!("{}-fixture-finding", reviewer.id),
        reviewer_id: reviewer.id.clone(),
        perspective: reviewer.perspective.clone(),
        severity: Severity::Major,
        category: "fixture".to_string(),
        title: "Fixture-directed review finding".to_string(),
        description:
            "The offline fake harness emitted this finding from an exact fixture directive."
                .to_string(),
        evidence: "CERBERUS_FAKE_FINDING".to_string(),
        citation: cerberus_schema::Citation {
            path: first_file.path.clone(),
            line: Some(1),
        },
        confidence: 1.0,
    }]
}

fn fake_usage(request: &ReviewRequest) -> TokenUsage {
    TokenUsage {
        prompt_tokens: (request.change.diff.len() / 4).max(1) as u64,
        completion_tokens: 64,
    }
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

fn dedupe_findings(findings: Vec<Finding>) -> Vec<Finding> {
    let mut seen = BTreeSet::new();
    let mut deduped = Vec::new();

    for finding in findings {
        let key = (
            finding.category.clone(),
            finding.title.clone(),
            finding.citation.path.clone(),
            finding.citation.line,
        );
        if seen.insert(key) {
            deduped.push(finding);
        }
    }

    deduped
}

fn aggregate_coverage(files: &[ChangedFile], artifacts: &[ReviewerArtifact]) -> Coverage {
    let files_reviewed = files
        .iter()
        .map(|file| file.path.clone())
        .collect::<BTreeSet<_>>();
    let mut files_with_findings = BTreeSet::new();

    for artifact in artifacts {
        for file in &artifact.coverage.files_with_findings {
            files_with_findings.insert(file.clone());
        }
    }

    Coverage {
        files_reviewed: files_reviewed.into_iter().collect(),
        files_with_findings: files_with_findings.into_iter().collect(),
    }
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

fn reserve_signals(artifacts: &[ReviewerArtifact]) -> Vec<ReserveSignal> {
    let mut reserves = BTreeSet::new();
    let has_pass = artifacts
        .iter()
        .any(|artifact| artifact.verdict == Verdict::Pass);
    let has_fail = artifacts
        .iter()
        .any(|artifact| artifact.verdict == Verdict::Fail);

    if has_pass && has_fail {
        reserves.insert(ReserveSignal::Disagreement);
    }
    if artifacts
        .iter()
        .any(|artifact| artifact.status != ReviewerStatus::Completed)
    {
        reserves.insert(ReserveSignal::DegradedReviewer);
    }
    if artifacts
        .iter()
        .flat_map(|artifact| &artifact.findings)
        .any(|finding| finding.confidence < 0.5)
    {
        reserves.insert(ReserveSignal::LowConfidence);
    }
    if artifacts
        .iter()
        .flat_map(|artifact| &artifact.findings)
        .any(|finding| finding.severity == Severity::Critical && finding.evidence.trim().len() < 10)
    {
        reserves.insert(ReserveSignal::CriticalWeakEvidence);
    }

    reserves.into_iter().collect()
}

fn coverage_for_request(files: &[ChangedFile], files_with_findings: Vec<String>) -> Coverage {
    Coverage {
        files_reviewed: files.iter().map(|file| file.path.clone()).collect(),
        files_with_findings,
    }
}

fn aggregate_cost(artifacts: &[ReviewerArtifact]) -> CostSummary {
    let mut per_reviewer = BTreeMap::new();
    let mut total_usd = 0.0;

    for artifact in artifacts {
        per_reviewer.insert(artifact.reviewer_id.clone(), artifact.cost_usd);
        total_usd += artifact.cost_usd;
    }

    CostSummary {
        total_usd,
        per_reviewer,
    }
}

fn summarize(
    verdict: Verdict,
    artifacts: &[ReviewerArtifact],
    finding_count: usize,
    override_applied: Option<&cerberus_schema::OverrideApproval>,
) -> String {
    if let Some(override_approval) = override_applied {
        return format!(
            "Override by {} for {}: {}.",
            override_approval.actor, override_approval.sha, override_approval.reason
        );
    }

    let degraded = artifacts
        .iter()
        .filter(|artifact| artifact.status != ReviewerStatus::Completed)
        .count();

    match (verdict, finding_count, degraded) {
        (Verdict::Pass, 0, 0) => "All fake reviewers passed.".to_string(),
        (Verdict::Skip, _, _) => "All fake reviewers skipped or degraded.".to_string(),
        (_, findings, degraded) if degraded > 0 => {
            format!("{findings} finding(s); {degraded} reviewer(s) degraded.")
        }
        (_, findings, _) => format!("{findings} finding(s)."),
    }
}

fn digest_json<T: serde::Serialize>(value: &T) -> Result<String, serde_json::Error> {
    let bytes = serde_json::to_vec(value)?;
    let digest = Sha256::digest(bytes);
    Ok(format!("{digest:x}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use cerberus_schema::{OverrideApproval, ReviewRequest, SchemaError};

    fn fixture(name: &str) -> ReviewRequest {
        let path = format!("../../fixtures/review-request/{name}.json");
        let raw = std::fs::read_to_string(path).expect("fixture readable");
        serde_json::from_str(&raw).expect("fixture parses")
    }

    #[test]
    fn local_diff_fixture_produces_fail_artifact_from_directive() {
        let request = fixture("local-diff");
        let artifact = review(&request, &default_config()).expect("review succeeds");

        assert_eq!(artifact.verdict, Verdict::Fail);
        assert_eq!(artifact.findings.len(), 1);
        assert!(!artifact.degraded);
        artifact.validate().expect("artifact validates");
    }

    #[test]
    fn clean_fixture_passes_without_findings() {
        let request = fixture("clean");
        let artifact = review(&request, &default_config()).expect("review succeeds");

        assert_eq!(artifact.verdict, Verdict::Pass);
        assert!(artifact.findings.is_empty());
    }

    #[test]
    fn degraded_fixture_records_skip_and_degraded_state() {
        let request = fixture("timeout-degraded");
        let artifact = review(&request, &default_config()).expect("review succeeds");

        assert_eq!(artifact.verdict, Verdict::Skip);
        assert!(artifact.degraded);
        assert!(artifact
            .reviewer_artifacts
            .iter()
            .all(|reviewer| reviewer.status == ReviewerStatus::Timeout));
        assert_eq!(artifact.stats.skip, 3);
        assert_eq!(artifact.reserves, vec![ReserveSignal::DegradedReviewer]);
    }

    #[test]
    fn override_records_pre_override_verdict_before_final_pass() {
        let mut request = fixture("local-diff");
        request.policy.override_approval = Some(OverrideApproval {
            actor: "maintainer".to_string(),
            sha: "localsha".to_string(),
            reason: "accepted for fixture replay".to_string(),
        });

        let artifact = review(&request, &default_config()).expect("review succeeds");

        assert_eq!(artifact.pre_override_verdict, Verdict::Fail);
        assert_eq!(artifact.verdict, Verdict::Pass);
        assert!(artifact.override_applied.is_some());
        artifact.validate().expect("artifact validates");
    }

    #[test]
    fn artifact_validation_rejects_mutated_override_sha() {
        let mut request = fixture("local-diff");
        request.policy.override_approval = Some(OverrideApproval {
            actor: "maintainer".to_string(),
            sha: "localsha".to_string(),
            reason: "accepted for fixture replay".to_string(),
        });
        let mut artifact = review(&request, &default_config()).expect("review succeeds");

        artifact
            .override_applied
            .as_mut()
            .expect("override exists")
            .sha = "othersha".to_string();

        assert!(matches!(
            artifact.validate(),
            Err(SchemaError::Mismatch {
                field: "override_applied.sha",
                ..
            })
        ));
    }

    #[test]
    fn artifact_validation_rejects_mutated_verdict() {
        let request = fixture("local-diff");
        let mut artifact = review(&request, &default_config()).expect("review succeeds");

        artifact.verdict = Verdict::Pass;

        assert!(matches!(
            artifact.validate(),
            Err(SchemaError::Inconsistent { field: "verdict" })
        ));
    }

    #[test]
    fn inline_comment_projection_is_derived_from_artifact_findings() {
        let request = fixture("local-diff");
        let artifact = review(&request, &default_config()).expect("review succeeds");
        let comments = render_inline_comment_candidates(&artifact);

        assert_eq!(comments.len(), 1);
        assert_eq!(comments[0].finding_id, artifact.findings[0].id);
        assert_eq!(comments[0].path, "src/lib.rs");
        assert!(comments[0].body.contains("CERBERUS_FAKE_FINDING"));
        comments[0].validate().expect("comment candidate validates");
    }
}
