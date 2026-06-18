use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

pub const REVIEW_REQUEST_VERSION: &str = "review-request.v1";
pub const REVIEW_CONFIG_VERSION: &str = "review-config.v1";
pub const REVIEWER_ARTIFACT_VERSION: &str = "reviewer-artifact.v1";
pub const REVIEW_RUN_ARTIFACT_VERSION: &str = "review-run-artifact.v1";
pub const INLINE_COMMENT_CANDIDATE_VERSION: &str = "inline-comment-candidate.v1";

#[derive(Debug, thiserror::Error)]
pub enum SchemaError {
    #[error("{field} must not be empty")]
    Empty { field: &'static str },
    #[error("{field} has unsupported version {actual:?}, expected {expected:?}")]
    Version {
        field: &'static str,
        actual: String,
        expected: &'static str,
    },
    #[error("review request must include at least one change file")]
    NoFiles,
    #[error("review config must include at least one reviewer")]
    NoReviewers,
    #[error("review run artifact must include at least one reviewer artifact")]
    NoReviewerArtifacts,
    #[error("{field} is missing required value")]
    Missing { field: &'static str },
    #[error("{field} mismatch: expected {expected:?}, got {actual:?}")]
    Mismatch {
        field: &'static str,
        expected: String,
        actual: String,
    },
    #[error("{field} is inconsistent with reviewer artifacts")]
    Inconsistent { field: &'static str },
    #[error("{field} must be between {min} and {max}, got {actual}")]
    OutOfRange {
        field: &'static str,
        min: f64,
        max: f64,
        actual: f64,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ReviewRequest {
    pub schema_version: String,
    pub request_id: String,
    pub source: ReviewSource,
    pub change: Change,
    pub context: ReviewContext,
    #[serde(default)]
    pub caller: Caller,
    #[serde(default)]
    pub policy: ReviewPolicy,
}

impl ReviewRequest {
    pub fn validate(&self) -> Result<(), SchemaError> {
        expect_version(
            "schema_version",
            &self.schema_version,
            REVIEW_REQUEST_VERSION,
        )?;
        non_empty("request_id", &self.request_id)?;
        self.source.validate()?;
        self.change.validate()?;
        self.validate_source_change_consistency()?;
        self.context.validate()?;
        self.caller.validate()?;
        self.policy.validate(
            self.change
                .head_sha
                .as_deref()
                .or_else(|| self.source.head_sha()),
        )?;
        Ok(())
    }

    fn validate_source_change_consistency(&self) -> Result<(), SchemaError> {
        expect_optional_match(
            "source.base_ref",
            self.source.base_ref(),
            self.change.base_ref.as_deref(),
        )?;
        expect_optional_match(
            "source.head_ref",
            self.source.head_ref(),
            self.change.head_ref.as_deref(),
        )?;
        expect_optional_match(
            "source.head_sha",
            self.source.head_sha(),
            self.change.head_sha.as_deref(),
        )
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ReviewSource {
    LocalDiff {
        repo_path: Option<String>,
    },
    GitRange {
        repository: Option<String>,
        base_ref: String,
        head_ref: String,
    },
    GithubPr {
        repository: String,
        pr_number: u64,
        base_ref: String,
        head_ref: String,
        head_sha: Option<String>,
    },
    Fixture {
        name: String,
    },
    External {
        system: String,
        id: String,
    },
}

impl ReviewSource {
    fn validate(&self) -> Result<(), SchemaError> {
        match self {
            ReviewSource::LocalDiff { .. } => Ok(()),
            ReviewSource::GitRange {
                base_ref, head_ref, ..
            } => {
                non_empty("source.base_ref", base_ref)?;
                non_empty("source.head_ref", head_ref)
            }
            ReviewSource::GithubPr {
                repository,
                base_ref,
                head_ref,
                ..
            } => {
                non_empty("source.repository", repository)?;
                non_empty("source.base_ref", base_ref)?;
                non_empty("source.head_ref", head_ref)
            }
            ReviewSource::Fixture { name } => non_empty("source.name", name),
            ReviewSource::External { system, id } => {
                non_empty("source.system", system)?;
                non_empty("source.id", id)
            }
        }
    }

    fn base_ref(&self) -> Option<&str> {
        match self {
            ReviewSource::GitRange { base_ref, .. } | ReviewSource::GithubPr { base_ref, .. } => {
                Some(base_ref)
            }
            ReviewSource::LocalDiff { .. }
            | ReviewSource::Fixture { .. }
            | ReviewSource::External { .. } => None,
        }
    }

    fn head_ref(&self) -> Option<&str> {
        match self {
            ReviewSource::GitRange { head_ref, .. } | ReviewSource::GithubPr { head_ref, .. } => {
                Some(head_ref)
            }
            ReviewSource::LocalDiff { .. }
            | ReviewSource::Fixture { .. }
            | ReviewSource::External { .. } => None,
        }
    }

    fn head_sha(&self) -> Option<&str> {
        match self {
            ReviewSource::GithubPr { head_sha, .. } => head_sha.as_deref(),
            ReviewSource::LocalDiff { .. }
            | ReviewSource::GitRange { .. }
            | ReviewSource::Fixture { .. }
            | ReviewSource::External { .. } => None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Change {
    pub title: String,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub base_ref: Option<String>,
    #[serde(default)]
    pub head_ref: Option<String>,
    #[serde(default)]
    pub head_sha: Option<String>,
    pub diff: String,
    pub files: Vec<ChangedFile>,
}

impl Change {
    fn validate(&self) -> Result<(), SchemaError> {
        non_empty("change.title", &self.title)?;
        non_empty("change.diff", &self.diff)?;
        if self.files.is_empty() {
            return Err(SchemaError::NoFiles);
        }
        for file in &self.files {
            file.validate()?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ChangedFile {
    pub path: String,
    pub status: FileStatus,
    #[serde(default)]
    pub additions: u64,
    #[serde(default)]
    pub deletions: u64,
}

impl ChangedFile {
    fn validate(&self) -> Result<(), SchemaError> {
        non_empty("file.path", &self.path)
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum FileStatus {
    Added,
    Modified,
    Deleted,
    Renamed,
    Copied,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReviewContext {
    #[serde(default)]
    pub summary: Option<String>,
    #[serde(default)]
    pub acceptance: Vec<String>,
    #[serde(default)]
    pub linked_artifacts: Vec<String>,
    #[serde(default)]
    pub metadata: BTreeMap<String, String>,
}

impl ReviewContext {
    fn validate(&self) -> Result<(), SchemaError> {
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Caller {
    pub name: String,
    pub run_id: String,
}

impl Default for Caller {
    fn default() -> Self {
        Self {
            name: "unknown".to_string(),
            run_id: "unknown".to_string(),
        }
    }
}

impl Caller {
    fn validate(&self) -> Result<(), SchemaError> {
        non_empty("caller.name", &self.name)?;
        non_empty("caller.run_id", &self.run_id)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ReviewPolicy {
    #[serde(default = "default_render_targets")]
    pub render_targets: Vec<RenderTarget>,
    #[serde(default)]
    pub allow_degraded: bool,
    #[serde(default)]
    pub max_cost_usd: Option<f64>,
    #[serde(default)]
    pub override_approval: Option<OverrideApproval>,
}

impl Default for ReviewPolicy {
    fn default() -> Self {
        Self {
            render_targets: default_render_targets(),
            allow_degraded: true,
            max_cost_usd: None,
            override_approval: None,
        }
    }
}

impl ReviewPolicy {
    fn validate(&self, expected_head_sha: Option<&str>) -> Result<(), SchemaError> {
        if let Some(max_cost_usd) = self.max_cost_usd {
            expect_range("policy.max_cost_usd", max_cost_usd, 0.0, f64::MAX)?;
        }
        if let Some(override_approval) = &self.override_approval {
            override_approval.validate()?;
            let expected = expected_head_sha.ok_or(SchemaError::Missing {
                field: "policy.override_approval.expected_head_sha",
            })?;
            if override_approval.sha != expected {
                return Err(SchemaError::Mismatch {
                    field: "policy.override_approval.sha",
                    expected: expected.to_string(),
                    actual: override_approval.sha.clone(),
                });
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct OverrideApproval {
    pub actor: String,
    pub sha: String,
    pub reason: String,
}

impl OverrideApproval {
    fn validate(&self) -> Result<(), SchemaError> {
        non_empty("override.actor", &self.actor)?;
        non_empty("override.sha", &self.sha)?;
        non_empty("override.reason", &self.reason)
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum RenderTarget {
    Markdown,
    Json,
    GithubReview,
}

fn default_render_targets() -> Vec<RenderTarget> {
    vec![RenderTarget::Markdown, RenderTarget::Json]
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ReviewConfig {
    pub schema_version: String,
    pub config_id: String,
    pub reviewers: Vec<ReviewerConfig>,
    #[serde(default = "default_confidence_min")]
    pub confidence_min: f64,
}

impl ReviewConfig {
    pub fn validate(&self) -> Result<(), SchemaError> {
        expect_version(
            "schema_version",
            &self.schema_version,
            REVIEW_CONFIG_VERSION,
        )?;
        non_empty("config_id", &self.config_id)?;
        if self.reviewers.is_empty() {
            return Err(SchemaError::NoReviewers);
        }
        expect_range("confidence_min", self.confidence_min, 0.0, 1.0)?;
        for reviewer in &self.reviewers {
            reviewer.validate()?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReviewerConfig {
    pub id: String,
    pub perspective: String,
    pub model: String,
    #[serde(default)]
    pub fake_behavior: FakeReviewerBehavior,
}

impl ReviewerConfig {
    fn validate(&self) -> Result<(), SchemaError> {
        non_empty("reviewer.id", &self.id)?;
        non_empty("reviewer.perspective", &self.perspective)?;
        non_empty("reviewer.model", &self.model)
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum FakeReviewerBehavior {
    Directive,
    Pass,
    Degraded,
}

impl Default for FakeReviewerBehavior {
    fn default() -> Self {
        Self::Directive
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ReviewerArtifact {
    pub schema_version: String,
    pub reviewer_id: String,
    pub perspective: String,
    pub model: String,
    pub status: ReviewerStatus,
    pub verdict: Verdict,
    pub summary: String,
    pub findings: Vec<Finding>,
    pub coverage: Coverage,
    pub usage: TokenUsage,
    pub cost_usd: f64,
    #[serde(default)]
    pub degraded_reason: Option<String>,
}

impl ReviewerArtifact {
    pub fn validate(&self) -> Result<(), SchemaError> {
        expect_version(
            "schema_version",
            &self.schema_version,
            REVIEWER_ARTIFACT_VERSION,
        )?;
        non_empty("reviewer_id", &self.reviewer_id)?;
        non_empty("perspective", &self.perspective)?;
        non_empty("model", &self.model)?;
        non_empty("summary", &self.summary)?;
        for finding in &self.findings {
            finding.validate()?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ReviewerStatus {
    Completed,
    Timeout,
    Error,
    Degraded,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Verdict {
    Pass,
    Warn,
    Fail,
    Skip,
}

impl Verdict {
    pub fn as_str(self) -> &'static str {
        match self {
            Verdict::Pass => "PASS",
            Verdict::Warn => "WARN",
            Verdict::Fail => "FAIL",
            Verdict::Skip => "SKIP",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Finding {
    pub id: String,
    pub reviewer_id: String,
    pub perspective: String,
    pub severity: Severity,
    pub category: String,
    pub title: String,
    pub description: String,
    pub evidence: String,
    pub citation: Citation,
    pub confidence: f64,
}

impl Finding {
    pub fn validate(&self) -> Result<(), SchemaError> {
        non_empty("finding.id", &self.id)?;
        non_empty("finding.reviewer_id", &self.reviewer_id)?;
        non_empty("finding.perspective", &self.perspective)?;
        non_empty("finding.category", &self.category)?;
        non_empty("finding.title", &self.title)?;
        non_empty("finding.description", &self.description)?;
        non_empty("finding.evidence", &self.evidence)?;
        self.citation.validate()
    }
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "snake_case")]
pub enum Severity {
    Info,
    Minor,
    Major,
    Critical,
}

impl Severity {
    pub fn as_str(self) -> &'static str {
        match self {
            Severity::Info => "info",
            Severity::Minor => "minor",
            Severity::Major => "major",
            Severity::Critical => "critical",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Citation {
    pub path: String,
    #[serde(default)]
    pub line: Option<u64>,
}

impl Citation {
    pub fn validate(&self) -> Result<(), SchemaError> {
        non_empty("citation.path", &self.path)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct InlineCommentCandidate {
    pub schema_version: String,
    pub finding_id: String,
    pub reviewer_id: String,
    pub perspective: String,
    pub path: String,
    pub line: u64,
    pub severity: Severity,
    pub body: String,
}

impl InlineCommentCandidate {
    pub fn validate(&self) -> Result<(), SchemaError> {
        expect_version(
            "schema_version",
            &self.schema_version,
            INLINE_COMMENT_CANDIDATE_VERSION,
        )?;
        non_empty("finding_id", &self.finding_id)?;
        non_empty("reviewer_id", &self.reviewer_id)?;
        non_empty("perspective", &self.perspective)?;
        non_empty("path", &self.path)?;
        non_empty("body", &self.body)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Coverage {
    pub files_reviewed: Vec<String>,
    pub files_with_findings: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct TokenUsage {
    pub prompt_tokens: u64,
    pub completion_tokens: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ReviewRunArtifact {
    pub schema_version: String,
    pub run_id: String,
    pub request_id: String,
    pub request_digest: String,
    pub config_digest: String,
    pub reviewed_head_sha: Option<String>,
    pub pre_override_verdict: Verdict,
    pub verdict: Verdict,
    pub summary: String,
    pub findings: Vec<Finding>,
    pub reviewer_artifacts: Vec<ReviewerArtifact>,
    pub stats: VerdictStats,
    pub coverage: Coverage,
    pub degraded: bool,
    pub reserves: Vec<ReserveSignal>,
    #[serde(default)]
    pub override_applied: Option<OverrideApproval>,
    pub cost: CostSummary,
}

impl ReviewRunArtifact {
    pub fn validate(&self) -> Result<(), SchemaError> {
        expect_version(
            "schema_version",
            &self.schema_version,
            REVIEW_RUN_ARTIFACT_VERSION,
        )?;
        non_empty("run_id", &self.run_id)?;
        non_empty("request_id", &self.request_id)?;
        non_empty("request_digest", &self.request_digest)?;
        non_empty("config_digest", &self.config_digest)?;
        non_empty("summary", &self.summary)?;
        if self.reviewer_artifacts.is_empty() {
            return Err(SchemaError::NoReviewerArtifacts);
        }
        for finding in &self.findings {
            finding.validate()?;
        }
        for artifact in &self.reviewer_artifacts {
            artifact.validate()?;
        }
        self.validate_replay_consistency()?;
        Ok(())
    }

    fn validate_replay_consistency(&self) -> Result<(), SchemaError> {
        let expected_stats = verdict_stats(&self.reviewer_artifacts);
        if self.stats != expected_stats {
            return Err(SchemaError::Inconsistent { field: "stats" });
        }

        let expected_findings = dedupe_findings(
            self.reviewer_artifacts
                .iter()
                .flat_map(|artifact| artifact.findings.clone())
                .collect(),
        );
        if self.findings != expected_findings {
            return Err(SchemaError::Inconsistent { field: "findings" });
        }

        let expected_pre_override = aggregate_verdict(&self.reviewer_artifacts, &expected_stats);
        if self.pre_override_verdict != expected_pre_override {
            return Err(SchemaError::Inconsistent {
                field: "pre_override_verdict",
            });
        }
        match &self.override_applied {
            Some(override_approval) => {
                override_approval.validate()?;
                let reviewed_head_sha =
                    self.reviewed_head_sha
                        .as_deref()
                        .ok_or(SchemaError::Missing {
                            field: "reviewed_head_sha",
                        })?;
                if override_approval.sha != reviewed_head_sha {
                    return Err(SchemaError::Mismatch {
                        field: "override_applied.sha",
                        expected: reviewed_head_sha.to_string(),
                        actual: override_approval.sha.clone(),
                    });
                }
                if !matches!(expected_pre_override, Verdict::Fail | Verdict::Warn)
                    || self.verdict != Verdict::Pass
                {
                    return Err(SchemaError::Inconsistent { field: "verdict" });
                }
            }
            None => {
                if self.verdict != expected_pre_override {
                    return Err(SchemaError::Inconsistent { field: "verdict" });
                }
            }
        }

        let expected_degraded = self
            .reviewer_artifacts
            .iter()
            .any(|artifact| artifact.status != ReviewerStatus::Completed);
        if self.degraded != expected_degraded {
            return Err(SchemaError::Inconsistent { field: "degraded" });
        }

        let expected_coverage = aggregate_coverage(&self.reviewer_artifacts);
        if self.coverage != expected_coverage {
            return Err(SchemaError::Inconsistent { field: "coverage" });
        }

        let expected_reserves = reserve_signals(&self.reviewer_artifacts);
        if self.reserves != expected_reserves {
            return Err(SchemaError::Inconsistent { field: "reserves" });
        }

        let expected_cost = aggregate_cost(&self.reviewer_artifacts);
        if !costs_match(&self.cost, &expected_cost) {
            return Err(SchemaError::Inconsistent { field: "cost" });
        }

        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CostSummary {
    pub total_usd: f64,
    pub per_reviewer: BTreeMap<String, f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct VerdictStats {
    pub total: u64,
    pub pass: u64,
    pub warn: u64,
    pub fail: u64,
    pub skip: u64,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "snake_case")]
pub enum ReserveSignal {
    Disagreement,
    LowConfidence,
    CriticalWeakEvidence,
    DegradedReviewer,
}

fn default_confidence_min() -> f64 {
    0.7
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

fn expect_optional_match(
    field: &'static str,
    expected: Option<&str>,
    actual: Option<&str>,
) -> Result<(), SchemaError> {
    if let (Some(expected), Some(actual)) = (expected, actual) {
        if expected != actual {
            return Err(SchemaError::Mismatch {
                field,
                expected: expected.to_string(),
                actual: actual.to_string(),
            });
        }
    }
    Ok(())
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

fn aggregate_coverage(artifacts: &[ReviewerArtifact]) -> Coverage {
    let mut files_reviewed = BTreeSet::new();
    let mut files_with_findings = BTreeSet::new();

    for artifact in artifacts {
        files_reviewed.extend(artifact.coverage.files_reviewed.iter().cloned());
        files_with_findings.extend(artifact.coverage.files_with_findings.iter().cloned());
    }

    Coverage {
        files_reviewed: files_reviewed.into_iter().collect(),
        files_with_findings: files_with_findings.into_iter().collect(),
    }
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

fn costs_match(actual: &CostSummary, expected: &CostSummary) -> bool {
    floats_close(actual.total_usd, expected.total_usd)
        && actual.per_reviewer.len() == expected.per_reviewer.len()
        && expected
            .per_reviewer
            .iter()
            .all(|(reviewer, expected_cost)| {
                actual
                    .per_reviewer
                    .get(reviewer)
                    .is_some_and(|actual_cost| floats_close(*actual_cost, *expected_cost))
            })
}

fn floats_close(left: f64, right: f64) -> bool {
    (left - right).abs() <= 0.000_000_001
}

#[cfg(test)]
mod tests {
    use super::*;

    fn valid_request() -> ReviewRequest {
        ReviewRequest {
            schema_version: REVIEW_REQUEST_VERSION.to_string(),
            request_id: "request".to_string(),
            source: ReviewSource::LocalDiff { repo_path: None },
            change: Change {
                title: "title".to_string(),
                description: None,
                base_ref: None,
                head_ref: None,
                head_sha: Some("headsha".to_string()),
                diff: "diff".to_string(),
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
            caller: Caller::default(),
            policy: ReviewPolicy::default(),
        }
    }

    #[test]
    fn rejects_empty_request_id() {
        let mut request = valid_request();
        request.request_id = String::new();

        assert!(matches!(
            request.validate(),
            Err(SchemaError::Empty {
                field: "request_id"
            })
        ));
    }

    #[test]
    fn rejects_mismatched_source_and_change_sha() {
        let mut request = valid_request();
        request.source = ReviewSource::GithubPr {
            repository: "misty-step/cerberus".to_string(),
            pr_number: 1,
            base_ref: "main".to_string(),
            head_ref: "feature".to_string(),
            head_sha: Some("source-sha".to_string()),
        };
        request.change.base_ref = Some("main".to_string());
        request.change.head_ref = Some("feature".to_string());
        request.change.head_sha = Some("change-sha".to_string());

        assert!(matches!(
            request.validate(),
            Err(SchemaError::Mismatch {
                field: "source.head_sha",
                ..
            })
        ));
    }

    #[test]
    fn rejects_override_for_wrong_head_sha() {
        let mut request = valid_request();
        request.policy.override_approval = Some(OverrideApproval {
            actor: "maintainer".to_string(),
            sha: "wrong-sha".to_string(),
            reason: "accepted risk".to_string(),
        });

        assert!(matches!(
            request.validate(),
            Err(SchemaError::Mismatch {
                field: "policy.override_approval.sha",
                ..
            })
        ));
    }
}
