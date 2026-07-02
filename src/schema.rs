use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const REVIEW_REQUEST_SCHEMA: &str = "cerberus.review_request.v1";
pub const REVIEW_ARTIFACT_SCHEMA: &str = "cerberus.review_artifact.v1";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReviewRequest {
    pub schema_version: String,
    pub request_id: String,
    pub source: Source,
    pub change: Change,
    #[serde(default)]
    pub context: RequestContext,
    #[serde(default)]
    pub policy: ReviewPolicy,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Source {
    pub kind: SourceKind,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub external_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub repo: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub uri: Option<String>,
    #[serde(default)]
    pub metadata: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum SourceKind {
    LocalDiff,
    GitRange,
    GithubPr,
    External,
    Fixture,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Change {
    pub title: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub base_ref: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub head_ref: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub head_sha: Option<String>,
    pub diff: Diff,
    #[serde(default)]
    pub files: Vec<ChangedFile>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Diff {
    #[serde(default = "default_diff_format")]
    pub format: String,
    pub body: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub digest: Option<String>,
}

fn default_diff_format() -> String {
    "unified".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ChangedFile {
    pub path: String,
    pub status: FileStatus,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub old_path: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub additions: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub deletions: Option<u32>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum FileStatus {
    Added,
    Modified,
    Removed,
    Renamed,
    Copied,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct RequestContext {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub summary: Option<String>,
    #[serde(default)]
    pub acceptance: Vec<String>,
    #[serde(default)]
    pub instructions: Vec<String>,
    #[serde(default)]
    pub artifacts: Vec<ContextArtifact>,
    #[serde(default)]
    pub workspaces: WorkspaceContext,
    #[serde(default)]
    pub local_runtime: Vec<RuntimeTarget>,
    #[serde(default)]
    pub remote_runtime: Vec<RemoteTarget>,
    #[serde(default)]
    pub metadata: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ContextArtifact {
    pub kind: String,
    pub uri: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub digest: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkspaceContext {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub head: Option<WorkspaceRef>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub base: Option<WorkspaceRef>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkspaceRef {
    pub kind: WorkspaceKind,
    pub path: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ref_name: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub sha: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum WorkspaceKind {
    Checkout,
    Packet,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct RuntimeTarget {
    pub kind: String,
    pub command: String,
    #[serde(default)]
    pub args: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cwd: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct RemoteTarget {
    pub name: String,
    pub url: String,
    #[serde(default)]
    pub allowed_methods: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReviewPolicy {
    #[serde(default = "default_allow_degraded")]
    pub allow_degraded: bool,
    #[serde(default = "default_timeout_ms")]
    pub timeout_ms: u64,
    #[serde(default)]
    pub allow_local_runtime: bool,
    #[serde(default)]
    pub external_research: ExternalResearchPolicy,
    #[serde(default)]
    pub render_targets: Vec<String>,
    #[serde(default)]
    pub allowed_env: Vec<String>,
}

impl Default for ReviewPolicy {
    fn default() -> Self {
        Self {
            allow_degraded: default_allow_degraded(),
            timeout_ms: default_timeout_ms(),
            allow_local_runtime: false,
            external_research: ExternalResearchPolicy::default(),
            render_targets: vec!["json".to_string(), "markdown".to_string()],
            allowed_env: Vec::new(),
        }
    }
}

fn default_allow_degraded() -> bool {
    true
}

fn default_timeout_ms() -> u64 {
    120_000
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ExternalResearchPolicy {
    #[default]
    Forbid,
    Allow,
    RequireCitations,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, schemars::JsonSchema)]
pub struct ContextCapabilities {
    pub diff: bool,
    pub repo_head: bool,
    pub repo_base: bool,
    pub local_runtime: bool,
    pub remote_runtime: bool,
    pub external_research: ExternalResearchPolicy,
}

impl ContextCapabilities {
    pub fn from_request(request: &ReviewRequest) -> Self {
        Self {
            diff: !request.change.diff.body.trim().is_empty(),
            repo_head: request.context.workspaces.head.is_some(),
            repo_base: request.context.workspaces.base.is_some(),
            local_runtime: request.policy.allow_local_runtime
                && !request.context.local_runtime.is_empty(),
            remote_runtime: !request.context.remote_runtime.is_empty(),
            external_research: request.policy.external_research.clone(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, schemars::JsonSchema)]
pub struct ReviewArtifact {
    pub schema_version: String,
    pub artifact_id: String,
    pub request_id: String,
    pub request_digest: String,
    pub lifecycle_state: LifecycleState,
    pub verdict: Verdict,
    pub context_capabilities: ContextCapabilities,
    pub summary: Summary,
    #[serde(default)]
    pub findings: Vec<Finding>,
    #[serde(default)]
    pub comments: Vec<Comment>,
    #[serde(default)]
    pub suggested_fixes: Vec<SuggestedFix>,
    #[serde(default)]
    pub citations: Vec<Citation>,
    #[serde(default)]
    pub receipts: Vec<Receipt>,
    pub run: RunInfo,
    #[serde(default)]
    pub errors: Vec<RunError>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum LifecycleState {
    Completed,
    CompletedDegraded,
    Failed,
    Skipped,
    Cancelled,
    Stale,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, schemars::JsonSchema)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Verdict {
    Pass,
    Warn,
    Fail,
    Skip,
}

impl Verdict {
    /// Uppercase display label — matches the wire representation
    /// (`SCREAMING_SNAKE_CASE`) so render and post surfaces don't hand-roll
    /// their own copy of this match.
    pub fn label(&self) -> &'static str {
        match self {
            Verdict::Pass => "PASS",
            Verdict::Warn => "WARN",
            Verdict::Fail => "FAIL",
            Verdict::Skip => "SKIP",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, schemars::JsonSchema)]
pub struct Summary {
    pub title: String,
    pub body: String,
    #[serde(default)]
    pub analysis: String,
    #[serde(default)]
    pub residual_risk: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, schemars::JsonSchema)]
pub struct Finding {
    pub id: String,
    pub severity: Severity,
    pub category: String,
    pub title: String,
    pub description: String,
    pub evidence: String,
    pub confidence: f32,
    #[serde(default)]
    pub anchors: Vec<Anchor>,
    #[serde(default)]
    pub citations: Vec<String>,
    #[serde(default)]
    pub suggested_fixes: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum Severity {
    Info,
    Minor,
    Major,
    Critical,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, schemars::JsonSchema)]
pub struct Anchor {
    pub kind: AnchorKind,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub path: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub line: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub start_line: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub end_line: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub hunk_digest: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum AnchorKind {
    Inline,
    File,
    Change,
    Run,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, schemars::JsonSchema)]
pub struct Comment {
    pub id: String,
    pub kind: CommentKind,
    pub intent: CommentIntent,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub finding_id: Option<String>,
    pub body: String,
    pub anchor: Anchor,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub dedupe_key: Option<String>,
    #[serde(default)]
    pub suggested_fixes: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum CommentKind {
    Inline,
    Contextual,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum CommentIntent {
    Finding,
    Note,
    Question,
    Summary,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, schemars::JsonSchema)]
pub struct SuggestedFix {
    pub id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub finding_id: Option<String>,
    pub applicability: FixApplicability,
    pub format: FixFormat,
    #[serde(default)]
    pub edits: Vec<Edit>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub diff: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum FixApplicability {
    Safe,
    NeedsReview,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum FixFormat {
    Replacement,
    UnifiedDiff,
    Instructions,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, schemars::JsonSchema)]
pub struct Edit {
    pub path: String,
    pub start_line: u32,
    pub end_line: u32,
    // Optional: only format=replacement edits carry replacement text. Real models
    // emit instruction/diff fixes with edits whose replacement is null/absent.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub replacement: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, schemars::JsonSchema)]
pub struct Citation {
    pub id: String,
    pub kind: CitationKind,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub uri: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub observed_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub digest: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub excerpt: Option<String>,
    #[serde(default)]
    pub used_by: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum CitationKind {
    Url,
    Paper,
    Doc,
    Command,
    Artifact,
    Repo,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, schemars::JsonSchema)]
pub struct Receipt {
    pub id: String,
    pub role: ReceiptRole,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub perspective: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub model: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub provider: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub harness: Option<String>,
    pub status: ReceiptStatus,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub verdict: Option<Verdict>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub summary: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub artifact_digest: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub transcript_uri: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub usage: Option<Usage>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<RunError>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ReceiptRole {
    Master,
    Reviewer,
    Critic,
    Researcher,
    Synthesizer,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ReceiptStatus {
    Completed,
    Timeout,
    Error,
    Skipped,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, schemars::JsonSchema)]
pub struct Usage {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub prompt_tokens: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub completion_tokens: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cost_usd: Option<f64>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct ReviewTelemetry {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub model: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub usage: Option<Usage>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cost_usd: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, schemars::JsonSchema)]
pub struct RunInfo {
    pub engine_version: String,
    pub config_digest: String,
    pub started_at: String,
    pub finished_at: String,
    pub duration_ms: u64,
    #[serde(
        default,
        deserialize_with = "optional_f64_from_number_or_string",
        skip_serializing_if = "Option::is_none"
    )]
    pub cost_usd: Option<f64>,
    pub coverage: Coverage,
}

fn optional_f64_from_number_or_string<'de, D>(deserializer: D) -> Result<Option<f64>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let Some(value) = Option::<serde_json::Value>::deserialize(deserializer)? else {
        return Ok(None);
    };
    match value {
        serde_json::Value::Null => Ok(None),
        serde_json::Value::Number(number) => number.as_f64().map(Some).ok_or_else(|| {
            serde::de::Error::custom("cost_usd number cannot be represented as f64")
        }),
        serde_json::Value::String(raw) => raw
            .parse::<f64>()
            .map(Some)
            .map_err(|_| serde::de::Error::custom("cost_usd string must parse as f64")),
        other => Err(serde::de::Error::custom(format!(
            "cost_usd must be a number, numeric string, or null, got {other}"
        ))),
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, schemars::JsonSchema)]
pub struct Coverage {
    pub files_reviewed: Vec<String>,
    pub files_with_findings: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, schemars::JsonSchema)]
pub struct RunError {
    pub scope: ErrorScope,
    pub code: String,
    pub message: String,
    pub retryable: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, schemars::JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum ErrorScope {
    Run,
    Reviewer,
    Research,
    Render,
    Adapter,
    Harness,
    Validation,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn run_cost_usd_accepts_legacy_string_but_serializes_number() {
        let run: RunInfo = serde_json::from_value(serde_json::json!({
            "engine_version": "test",
            "config_digest": "sha256:test",
            "started_at": "0",
            "finished_at": "1",
            "duration_ms": 1,
            "cost_usd": "0.42",
            "coverage": {
                "files_reviewed": [],
                "files_with_findings": []
            }
        }))
        .unwrap();

        assert_eq!(run.cost_usd, Some(0.42));
        let serialized = serde_json::to_value(&run).unwrap();
        assert_eq!(serialized["cost_usd"], serde_json::json!(0.42));
    }
}
