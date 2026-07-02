use std::path::Path;

use crate::schema::{ContextCapabilities, ReviewRequest};

/// Review doctrine — the "what to hunt" vocabulary the master reviewer and any
/// runtime lane draw from. Distilled from the Harness Kit lens bench
/// (`harnesses/shared/references/lenses.md`) so the interactive `/code-review`
/// skill and this production runner share one doctrine and do not drift. Edit
/// the bench there first, then mirror the distilled subset here. Fowler smell
/// curation credit: Matt Pocock's `/review` baseline; smells from *Refactoring*
/// Ch.3. Kept as runtime *vocabulary*, not fixed personas — Cerberus still
/// designs any lane from the diff at runtime.
pub(crate) const REVIEW_DOCTRINE: &str = include_str!("review_doctrine.md");

const ARTIFACT_FIELD_PATHS: &[&str] = &[
    "schema_version",
    "artifact_id",
    "request_id",
    "request_digest",
    "lifecycle_state",
    "verdict",
    "context_capabilities.diff",
    "context_capabilities.repo_head",
    "context_capabilities.repo_base",
    "context_capabilities.local_runtime",
    "context_capabilities.remote_runtime",
    "context_capabilities.external_research",
    "summary",
    "summary.title",
    "summary.body",
    "summary.analysis",
    "summary.residual_risk",
    "summary.residual_risk[]",
    "findings[]",
    "findings[].id",
    "findings[].severity",
    "findings[].category",
    "findings[].title",
    "findings[].description",
    "findings[].evidence",
    "findings[].confidence",
    "findings[].anchors[].kind",
    "findings[].anchors[].path",
    "findings[].anchors[].line",
    "findings[].anchors[].start_line",
    "findings[].anchors[].end_line",
    "findings[].anchors[].hunk_digest",
    "findings[].citations[]",
    "findings[].suggested_fixes[]",
    "comments[]",
    "comments[].id",
    "comments[].kind",
    "comments[].intent",
    "comments[].finding_id",
    "comments[].body",
    "comments[].anchor.kind",
    "comments[].anchor.path",
    "comments[].anchor.line",
    "comments[].anchor.start_line",
    "comments[].anchor.end_line",
    "comments[].anchor.hunk_digest",
    "comments[].dedupe_key",
    "comments[].suggested_fixes[]",
    "suggested_fixes[]",
    "suggested_fixes[].id",
    "suggested_fixes[].finding_id",
    "suggested_fixes[].applicability",
    "suggested_fixes[].format",
    "suggested_fixes[].edits[].path",
    "suggested_fixes[].edits[].start_line",
    "suggested_fixes[].edits[].end_line",
    "suggested_fixes[].edits[].replacement",
    "suggested_fixes[].diff",
    "citations[]",
    "citations[].id",
    "citations[].kind",
    "citations[].title",
    "citations[].uri",
    "citations[].observed_at",
    "citations[].digest",
    "citations[].excerpt",
    "citations[].used_by[]",
    "receipts[]",
    "receipts[].id",
    "receipts[].role",
    "receipts[].perspective",
    "receipts[].model",
    "receipts[].provider",
    "receipts[].harness",
    "receipts[].status",
    "receipts[].verdict",
    "receipts[].summary",
    "receipts[].artifact_digest",
    "receipts[].transcript_uri",
    "receipts[].usage.prompt_tokens",
    "receipts[].usage.completion_tokens",
    "receipts[].usage.cost_usd",
    "receipts[].error.scope",
    "receipts[].error.code",
    "receipts[].error.message",
    "receipts[].error.retryable",
    "run",
    "run.engine_version",
    "run.config_digest",
    "run.started_at",
    "run.finished_at",
    "run.duration_ms",
    "run.cost_usd",
    "run.coverage.files_reviewed[]",
    "run.coverage.files_with_findings[]",
    "errors[].scope",
    "errors[].code",
    "errors[].message",
    "errors[].retryable",
];

#[cfg(test)]
const ARTIFACT_CONTRACT_GROUPING_PATHS: &[&str] = &[
    "summary",
    "summary.residual_risk",
    "findings[]",
    "comments[]",
    "suggested_fixes[]",
    "citations[]",
    "receipts[]",
    "run",
];

const ARTIFACT_ENUM_AND_REFERENCE_RULES: &[&str] = &[
    "lifecycle_state must be completed, completed_degraded, failed, skipped, cancelled, or stale",
    "verdict must be PASS, WARN, FAIL, or SKIP",
    "severity must be info, minor, major, or critical",
    "findings[].confidence must be a JSON number from 0.0 to 1.0, never a label such as low, medium, or high",
    "comments[].kind must be inline or contextual",
    "comments[].intent must be finding, note, question, or summary",
    "anchor.kind must be inline, file, change, or run",
    "suggested_fixes[].applicability must be safe or needs_review",
    "suggested_fixes[].format must be instructions, replacement, or unified_diff",
    "citations[].kind must be url, paper, doc, command, artifact, or repo",
    "receipts[].role must be master, reviewer, critic, researcher, or synthesizer",
    "receipts[].status must be completed, timeout, error, or skipped",
    "all cost_usd fields must be JSON numbers or null, never strings",
    "findings[].citations[] values must name top-level citations[].id values",
    "findings[].suggested_fixes[] values must name top-level suggested_fixes[].id values",
    "comments[].finding_id values must name existing findings[].id values",
    "comments[].suggested_fixes[] values must name top-level suggested_fixes[].id values",
    "citations[].used_by[] values must name findings[].id values only",
    "suggested_fixes[].finding_id values must name existing findings[].id values",
];

#[cfg(test)]
const VALIDATION_FIXTURE_RULES: &[ValidationFixtureRule] = &[
    ValidationFixtureRule {
        fixture: "fixtures/harness/invalid-unknown-finding-id.txt",
        prompt_rule: "comments[].finding_id values must name existing findings[].id values",
    },
    ValidationFixtureRule {
        fixture: "fixtures/harness/invalid-unknown-suggested-fix.txt",
        prompt_rule: "comments[].suggested_fixes[] values must name top-level suggested_fixes[].id values",
    },
    ValidationFixtureRule {
        fixture: "fixtures/harness/invalid-orphan-suggested-fix.txt",
        prompt_rule: "top-level suggested_fixes without finding_id must be referenced by a finding or comment",
    },
];

const ARTIFACT_VALIDATION_RULES: &[&str] = &[
    "request_digest must equal the canonical ReviewRequest digest",
    "context_capabilities must not overstate the request context",
    "inline anchors must reference files present in the request change",
    "URL citations require observed_at",
    "nonzero or timeout substrate exits require completed_degraded, failed, or cancelled lifecycle plus timeout/error receipt",
    "top-level suggested_fixes without finding_id must be referenced by a finding or comment",
];

const LANE_EVIDENCE_SYNTHESIS_RULES: &[&str] = &[
    "ReviewerLaneReceipt.v1 is lane evidence, not an output artifact",
    "child-lane claims must be synthesized into the single ReviewArtifact.v1 and represented in receipts[] when used",
    "child-lane evidence must not raise context_capabilities beyond the ReviewRequest context",
    "child-lane findings still need concrete anchors, citations, and suggested_fix references that pass validation",
    "failed, timeout, or skipped child lanes belong in receipts[] and summary.residual_risk; they do not block emitting a completed_degraded artifact when the master can still judge the diff",
];

#[cfg(test)]
struct ValidationFixtureRule {
    fixture: &'static str,
    prompt_rule: &'static str,
}

fn artifact_contract_checklist() -> String {
    format!(
        "ReviewArtifact.v1 generated contract. Fields: {}. Enum/reference rules: {}. Validation rules checked by fixtures: {}.",
        ARTIFACT_FIELD_PATHS.join(", "),
        ARTIFACT_ENUM_AND_REFERENCE_RULES.join("; "),
        ARTIFACT_VALIDATION_RULES.join("; ")
    )
    + " Lane evidence synthesis rules: "
    + &LANE_EVIDENCE_SYNTHESIS_RULES.join("; ")
    + "."
}

pub fn build_master_prompt(
    request: &ReviewRequest,
    capabilities: &ContextCapabilities,
    request_digest: &str,
    out_path: &Path,
) -> Result<String, serde_json::Error> {
    let request_json = serde_json::to_string_pretty(request)?;
    let capabilities_json = serde_json::to_string_pretty(capabilities)?;
    let contract_checklist = artifact_contract_checklist();
    let out_path = out_path.display();
    Ok(format!(
        r#"You are Cerberus, the master code reviewer.

Mission:
- Review only from the context actually available.
- If repo_head is true, inspect the repository checkout directly before judging. At minimum, read changed files plus relevant nearby tests/callers/configs when they exist.
- If repo_head is false, stay diff-only and do not imply repository inspection.
- If repo_base is true, compare relevant base files against head before making regression or behavior-change claims. If repo_base is false, do not imply base checkout inspection.
- If local_runtime is true, runtime probe transcripts are attached as context artifacts; cite only the transcript evidence actually present. If local_runtime is false, do not claim tests, builds, app runs, or local QA.
- You may dynamically launch subagents if the selected substrate supports doing so and it improves the review.
- Do not rely on predefined reviewer personas. Design any lane at runtime from the diff and context.
- If you launch a lane, give it explicit objective, scope, allowed context, system prompt, and output shape.
- If ReviewerLaneReceipt.v1 lane evidence is attached, use it only as evidence to synthesize the final ReviewArtifact.v1; do not let child-lane claims bypass anchors, citations, context truth, receipt status, or validation.
- Synthesize evidence into one durable ReviewArtifact.v1.
- Do not make architectural, runtime, security, or dependency claims without concrete evidence.
- External research is allowed only if the request policy permits it. External claims require citations.
- Blocking findings must cite concrete anchors.
- PASS requires enough inspected evidence for the available context. If repo_head is true but direct checkout inspection fails or is skipped, use completed_degraded or WARN and record why.
- Emit your review by writing one ReviewArtifact.v1 object to the file at {out_path} using your write tool. That file is your only deliverable: it must hold exactly one raw JSON object and nothing else — no Markdown fences, no prose. Overwrite it completely if it already exists.

Review doctrine:
{review_doctrine}

Required ReviewArtifact.v1 fields:
- schema_version: "cerberus.review_artifact.v1"
- artifact_id: a unique non-placeholder string for this run
- request_id: "{request_id}"
- request_digest: "{request_digest}"
- lifecycle_state: one of completed, completed_degraded, failed, skipped, cancelled, stale
- verdict: one of PASS, WARN, FAIL, SKIP
- context_capabilities: copy the ContextCapabilities object below exactly
- summary: object with title, body, analysis, residual_risk array
	- findings: array; every finding needs id, severity, category, title, description, evidence, confidence, anchors, citations, suggested_fixes
	- comments: array; inline comments must use anchor.kind "inline"
	- findings[].citations and findings[].suggested_fixes must contain string ids only; put full Citation and SuggestedFix objects in the top-level arrays
	- suggested_fixes: array of full SuggestedFix objects
	- citations: array of full Citation objects; URL citations require observed_at
- receipts: include at least receipt-master with role "master", harness "opencode", status "completed", verdict, and a non-placeholder summary of what evidence you inspected
- run: include engine_version "cerberus-opencode", config_digest "sha256:prompt-only", started_at "0", finished_at "0", duration_ms 0, cost_usd null or a JSON number, and coverage
- errors: array

Coverage requirements:
- run.coverage.files_reviewed must list only files you actually inspected from the diff or checkout.
- run.coverage.files_with_findings must list files with findings.
- If repo_head is true and you do not inspect checkout files directly, do not return PASS; use WARN or completed_degraded and explain why.
- If you only inspect the diff from the request, say so in summary.residual_risk.
- Empty findings/comments/suggested_fixes/citations arrays are valid when there are no actionable issues.
- Do not claim tests, runtime QA, base checkout inspection, or external research unless the request context actually provides it.

Request digest: {request_digest}

{contract_checklist}

ContextCapabilities:
{capabilities_json}

ReviewRequest:
{request_json}
"#,
        request_id = request.request_id.as_str(),
        request_digest = request_digest,
        contract_checklist = contract_checklist,
        capabilities_json = capabilities_json,
        request_json = request_json,
        review_doctrine = REVIEW_DOCTRINE
    ))
}

pub fn build_opencode_message(
    request: &ReviewRequest,
    capabilities: &ContextCapabilities,
    request_digest: &str,
    out_path: &Path,
) -> Result<String, serde_json::Error> {
    let capabilities_json = serde_json::to_string(capabilities)?;
    let contract_checklist = artifact_contract_checklist();
    Ok(format!(
        "You are Cerberus, the master code reviewer. Read the attached ReviewRequest.v1 JSON file. Request id: {request_id}. Request digest: {request_digest}. ContextCapabilities: {capabilities_json}. If repo_head is true, explore the repository thoroughly and autonomously: use read, grep, glob, and the shell (ripgrep, ast-grep, git log/diff/blame) to understand the change in the context of the whole codebase and its history. The attached diff is a starting point, not your only evidence, and there is no fixed read budget. Be thorough but decisive: inspect the changed files and the code they directly touch — callers, callees, tests, and related config — then STOP exploring and emit your artifact. You do not need to read the entire repository, and you are on a wall-clock limit: producing one complete, grounded artifact is the objective, and an exploration that never emits an artifact is a failed review. If repo_base is true, compare relevant base files before making regression or behavior-change claims. Review like a senior engineer: prioritize correctness, security, and behavior regressions over style; ground every finding in a specific line you actually inspected and anchor it there; prefer a few high-signal findings over many low-value ones; never invent issues, and if the change is clean return PASS with empty findings; calibrate severity honestly and record what you did not inspect in summary.residual_risk. Draw on this review doctrine — the vocabulary of what to hunt — while you review: {review_doctrine} Use the shell only for read-only exploration; do not run builds, tests, applications, or network probes as evidence, and do not claim test, build, runtime, or QA results, unless local_runtime or remote_runtime is true (then rely only on the attached transcripts). If ReviewerLaneReceipt.v1 evidence is attached, synthesize it into your single ReviewArtifact.v1 and receipts[]; do not let child-lane claims bypass anchors, citations, context truth, or validation. Set run.coverage.files_reviewed to only files you actually inspected; if you skip changed files because of limits, record that reduced scope in lifecycle_state and summary.residual_risk. {contract_checklist} Emit your review by writing one ReviewArtifact.v1 object to the file at {out_path} using your write tool — that file is your only deliverable. It must hold exactly one raw JSON object and nothing else: no Markdown fences, no prose, no surrounding text. Set request_id and request_digest to the exact values above. Overwrite the file completely if it already exists, and once it holds the complete valid artifact you are done.",
        request_id = request.request_id.as_str(),
        request_digest = request_digest,
        capabilities_json = capabilities_json,
        contract_checklist = contract_checklist,
        out_path = out_path.display(),
        review_doctrine = REVIEW_DOCTRINE,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet;
    use std::path::Path;

    fn out_path() -> &'static Path {
        Path::new("/work/repo/review-artifact.json")
    }

    use crate::schema::{
        Anchor, AnchorKind, Citation, CitationKind, Comment, CommentIntent, CommentKind, Coverage,
        Edit, ErrorScope, ExternalResearchPolicy, Finding, FixApplicability, FixFormat,
        LifecycleState, Receipt, ReceiptRole, ReceiptStatus, ReviewArtifact, RunError, RunInfo,
        Severity, SuggestedFix, Summary, Usage, Verdict, REVIEW_ARTIFACT_SCHEMA,
    };

    #[test]
    fn prompts_embed_generated_artifact_contract() {
        let request = minimal_request();
        let capabilities = ContextCapabilities::from_request(&request);
        let prompt =
            build_master_prompt(&request, &capabilities, "sha256:test", out_path()).unwrap();
        let message =
            build_opencode_message(&request, &capabilities, "sha256:test", out_path()).unwrap();
        let contract = artifact_contract_checklist();

        assert!(prompt.contains(&contract));
        assert!(message.contains(&contract));
        for field_path in ARTIFACT_FIELD_PATHS {
            assert!(
                contract.contains(field_path),
                "missing field path {field_path}"
            );
        }
        for rule in ARTIFACT_ENUM_AND_REFERENCE_RULES
            .iter()
            .chain(ARTIFACT_VALIDATION_RULES)
            .chain(LANE_EVIDENCE_SYNTHESIS_RULES)
        {
            assert!(contract.contains(rule), "missing artifact rule {rule}");
        }
    }

    #[test]
    fn opencode_message_drops_exploration_cap_and_adds_review_craft() {
        let request = minimal_request();
        let capabilities = ContextCapabilities::from_request(&request);
        let message =
            build_opencode_message(&request, &capabilities, "sha256:test", out_path()).unwrap();
        assert!(
            !message.contains("at most eight"),
            "the fixture-era read cap must be gone"
        );
        assert!(
            !message.contains("stop tool use and produce the final artifact immediately"),
            "the single-round stop instruction must be gone"
        );
        assert!(message.contains("explore the repository thoroughly and autonomously"));
        assert!(message.contains("Review like a senior engineer"));
    }

    #[test]
    fn prompts_embed_review_doctrine() {
        let request = minimal_request();
        let capabilities = ContextCapabilities::from_request(&request);
        let master =
            build_master_prompt(&request, &capabilities, "sha256:test", out_path()).unwrap();
        let message =
            build_opencode_message(&request, &capabilities, "sha256:test", out_path()).unwrap();
        // Both surfaces must carry the same distilled doctrine so the production
        // runner does not drift from the /code-review lens bench.
        for prompt in [&master, &message] {
            assert!(
                prompt.contains("Plausible-but-wrong"),
                "doctrine: plausible-but-wrong vocabulary must be embedded"
            );
            assert!(
                prompt.contains("Feature Envy"),
                "doctrine: Fowler smell vocabulary must be embedded"
            );
            assert!(
                prompt.contains("code judo"),
                "doctrine: structural-ambition bar must be embedded"
            );
            // Backlog 023: the mandatory model-boundary dimension must reach
            // both prompt surfaces the same way every other doctrine section
            // does -- named vocabulary embedded in the shared doctrine text,
            // not a hardcoded persona.
            assert!(
                prompt.contains(
                    "heuristic-where-a-model-belongs-and-model-where-deterministic-code-belongs"
                ),
                "doctrine: the mandatory model-boundary dimension must be embedded"
            );
        }
    }

    #[test]
    fn prompts_instruct_file_emission_not_raw_stdout() {
        let request = minimal_request();
        let capabilities = ContextCapabilities::from_request(&request);
        let message =
            build_opencode_message(&request, &capabilities, "sha256:test", out_path()).unwrap();
        let master =
            build_master_prompt(&request, &capabilities, "sha256:test", out_path()).unwrap();
        for prompt in [&message, &master] {
            assert!(
                prompt.contains("/work/repo/review-artifact.json"),
                "emission target path must be named in the prompt"
            );
            assert!(
                prompt.contains("your write tool"),
                "the agent must be told to write the artifact as a file"
            );
        }
        // The raw-stdout / first-character marker contract is gone: emission is a file now.
        assert!(!message.contains("first character must be"));
        assert!(!master.contains("first output character must be"));
    }

    #[test]
    fn prompts_instruct_numeric_confidence() {
        let request = minimal_request();
        let capabilities = ContextCapabilities::from_request(&request);
        let message =
            build_opencode_message(&request, &capabilities, "sha256:test", out_path()).unwrap();
        assert!(
            message.contains("findings[].confidence must be a JSON number from 0.0 to 1.0"),
            "the production prompt must prevent confidence labels like high/medium/low"
        );
    }

    #[test]
    fn prompts_instruct_lane_evidence_synthesis() {
        let request = minimal_request();
        let capabilities = ContextCapabilities::from_request(&request);
        let message =
            build_opencode_message(&request, &capabilities, "sha256:test", out_path()).unwrap();
        let master =
            build_master_prompt(&request, &capabilities, "sha256:test", out_path()).unwrap();
        for prompt in [&message, &master] {
            assert!(prompt.contains("ReviewerLaneReceipt.v1"));
            assert!(prompt.contains("single ReviewArtifact.v1"));
            assert!(prompt.contains("must not raise context_capabilities"));
            assert!(prompt.contains("do not let child-lane claims bypass"));
        }
    }

    #[test]
    fn artifact_contract_covers_validation_fixture_failures() {
        let contract = artifact_contract_checklist();
        for fixture_rule in VALIDATION_FIXTURE_RULES {
            assert!(
                std::path::Path::new(fixture_rule.fixture).is_file(),
                "validation fixture {} should exist",
                fixture_rule.fixture
            );
            assert!(
                contract.contains(fixture_rule.prompt_rule),
                "prompt contract should cover validation fixture {} with rule {:?}",
                fixture_rule.fixture,
                fixture_rule.prompt_rule
            );
        }
    }

    #[test]
    fn artifact_contract_covers_serialized_review_artifact_shape() {
        let value = serde_json::to_value(representative_artifact()).unwrap();
        let serialized_paths = serialized_field_paths(&value);
        let contract_paths = ARTIFACT_FIELD_PATHS
            .iter()
            .map(|path| (*path).to_string())
            .collect::<BTreeSet<_>>();
        let missing = serialized_paths
            .difference(&contract_paths)
            .cloned()
            .collect::<Vec<_>>();
        let allowed_grouping_paths = ARTIFACT_CONTRACT_GROUPING_PATHS
            .iter()
            .map(|path| (*path).to_string())
            .collect::<BTreeSet<_>>();
        let stale = contract_paths
            .difference(&serialized_paths)
            .filter(|path| !allowed_grouping_paths.contains(*path))
            .cloned()
            .collect::<Vec<_>>();

        assert!(
            missing.is_empty(),
            "prompt contract missing serialized ReviewArtifact paths: {missing:?}"
        );
        assert!(
            stale.is_empty(),
            "prompt contract contains stale ReviewArtifact paths: {stale:?}"
        );
    }

    fn minimal_request() -> ReviewRequest {
        crate::test_support::minimal_review_request()
    }

    fn representative_artifact() -> ReviewArtifact {
        ReviewArtifact {
            schema_version: REVIEW_ARTIFACT_SCHEMA.to_string(),
            artifact_id: "artifact-1".to_string(),
            request_id: "req-1".to_string(),
            request_digest: "sha256:test".to_string(),
            lifecycle_state: LifecycleState::CompletedDegraded,
            verdict: Verdict::Warn,
            context_capabilities: ContextCapabilities {
                diff: true,
                repo_head: true,
                repo_base: true,
                local_runtime: true,
                remote_runtime: true,
                external_research: ExternalResearchPolicy::RequireCitations,
            },
            summary: Summary {
                title: "title".to_string(),
                body: "body".to_string(),
                analysis: "analysis".to_string(),
                residual_risk: vec!["risk".to_string()],
            },
            findings: vec![Finding {
                id: "finding-1".to_string(),
                severity: Severity::Major,
                category: "correctness".to_string(),
                title: "finding".to_string(),
                description: "description".to_string(),
                evidence: "evidence".to_string(),
                confidence: 0.9,
                anchors: vec![Anchor {
                    kind: AnchorKind::Inline,
                    path: Some("src/lib.rs".to_string()),
                    line: Some(1),
                    start_line: Some(1),
                    end_line: Some(1),
                    hunk_digest: Some("sha256:hunk".to_string()),
                }],
                citations: vec!["citation-1".to_string()],
                suggested_fixes: vec!["fix-1".to_string()],
            }],
            comments: vec![Comment {
                id: "comment-1".to_string(),
                kind: CommentKind::Inline,
                intent: CommentIntent::Finding,
                finding_id: Some("finding-1".to_string()),
                body: "comment".to_string(),
                anchor: Anchor {
                    kind: AnchorKind::Inline,
                    path: Some("src/lib.rs".to_string()),
                    line: Some(1),
                    start_line: Some(1),
                    end_line: Some(1),
                    hunk_digest: Some("sha256:hunk".to_string()),
                },
                dedupe_key: Some("dedupe".to_string()),
                suggested_fixes: vec!["fix-1".to_string()],
            }],
            suggested_fixes: vec![SuggestedFix {
                id: "fix-1".to_string(),
                finding_id: Some("finding-1".to_string()),
                applicability: FixApplicability::NeedsReview,
                format: FixFormat::UnifiedDiff,
                edits: vec![Edit {
                    path: "src/lib.rs".to_string(),
                    start_line: 1,
                    end_line: 1,
                    replacement: Some("replacement".to_string()),
                }],
                diff: Some("diff --git a/src/lib.rs b/src/lib.rs\n".to_string()),
            }],
            citations: vec![Citation {
                id: "citation-1".to_string(),
                kind: CitationKind::Url,
                title: Some("doc".to_string()),
                uri: Some("https://example.invalid/doc".to_string()),
                observed_at: Some("2026-06-20T00:00:00Z".to_string()),
                digest: Some("sha256:citation".to_string()),
                excerpt: Some("excerpt".to_string()),
                used_by: vec!["finding-1".to_string()],
            }],
            receipts: vec![Receipt {
                id: "receipt-master".to_string(),
                role: ReceiptRole::Master,
                perspective: Some("master".to_string()),
                model: Some("openrouter/model".to_string()),
                provider: Some("openrouter".to_string()),
                harness: Some("opencode".to_string()),
                status: ReceiptStatus::Error,
                verdict: Some(Verdict::Warn),
                summary: Some("inspected diff".to_string()),
                artifact_digest: Some("sha256:artifact".to_string()),
                transcript_uri: Some("target/cerberus/transcript.txt".to_string()),
                usage: Some(Usage {
                    prompt_tokens: Some(100),
                    completion_tokens: Some(50),
                    cost_usd: Some(0.01),
                }),
                error: Some(run_error()),
            }],
            run: RunInfo {
                engine_version: "test".to_string(),
                config_digest: "sha256:config".to_string(),
                started_at: "0".to_string(),
                finished_at: "1".to_string(),
                duration_ms: 1,
                cost_usd: Some(0.01),
                coverage: Coverage {
                    files_reviewed: vec!["src/lib.rs".to_string()],
                    files_with_findings: vec!["src/lib.rs".to_string()],
                },
            },
            errors: vec![run_error()],
        }
    }

    fn run_error() -> RunError {
        RunError {
            scope: ErrorScope::Harness,
            code: "example".to_string(),
            message: "example".to_string(),
            retryable: false,
        }
    }

    fn serialized_field_paths(value: &serde_json::Value) -> BTreeSet<String> {
        let mut paths = BTreeSet::new();
        collect_serialized_field_paths(value, "", &mut paths);
        paths
    }

    fn collect_serialized_field_paths(
        value: &serde_json::Value,
        prefix: &str,
        out: &mut BTreeSet<String>,
    ) {
        match value {
            serde_json::Value::Object(object) => {
                for (key, value) in object {
                    let path = if prefix.is_empty() {
                        key.clone()
                    } else {
                        format!("{prefix}.{key}")
                    };
                    collect_serialized_field_paths(value, &path, out);
                }
            }
            serde_json::Value::Array(items) => {
                let path = format!("{prefix}[]");
                if let Some(first) = items.first() {
                    collect_serialized_field_paths(first, &path, out);
                } else {
                    out.insert(path);
                }
            }
            _ => {
                out.insert(prefix.to_string());
            }
        }
    }
}
