//! Regenerates `schemas/review-artifact.example.json`, the canonical
//! `ReviewArtifact.v1` fixture (backlog 035). Built from the live struct, not
//! hand-typed, so it can never silently drift from the real shape. Every
//! optional field is populated at least once so the fixture exercises the
//! full schema, including the fields a minimal review never touches.
//!
//! Run: cargo run --example gen_review_artifact_fixture > schemas/review-artifact.example.json
//!
//! This is also the documented regeneration source for Crucible's
//! `crucible-core/tests/fixtures/cerberus-artifact.json` -- see README.md.

use cerberus::*;

fn main() {
    let artifact = ReviewArtifact {
        schema_version: REVIEW_ARTIFACT_SCHEMA.to_string(),
        artifact_id: "artifact-canonical-001".to_string(),
        request_id: "req-canonical-001".to_string(),
        request_digest: "sha256:canonical-request-digest".to_string(),
        lifecycle_state: schema::LifecycleState::Completed,
        verdict: schema::Verdict::Warn,
        context_capabilities: schema::ContextCapabilities {
            diff: true,
            repo_head: true,
            repo_base: false,
            local_runtime: false,
            remote_runtime: false,
            external_research: schema::ExternalResearchPolicy::Allow,
        },
        summary: schema::Summary {
            title: "One correctness concern, otherwise clean".to_string(),
            body: "The guard avoids division by zero, but returning 0.0 silently changes \
                   the mathematical meaning and may hide caller bugs."
                .to_string(),
            analysis: "Reviewed the full file for related call sites; none distinguish a \
                       real zero ratio from this sentinel."
                .to_string(),
            residual_risk: vec!["Call sites outside this file were not inspected.".to_string()],
        },
        findings: vec![schema::Finding {
            id: "finding-001".to_string(),
            severity: schema::Severity::Major,
            category: "correctness".to_string(),
            title: "Silent zero return may mask invalid denominator".to_string(),
            description: "The new branch returns 0.0 for every zero denominator. If callers \
                          distinguish a true zero ratio from invalid input, this will \
                          silently produce a plausible but wrong result."
                .to_string(),
            evidence: "The changed hunk adds `if denominator == 0.0 { return 0.0; }` before \
                       the existing division."
                .to_string(),
            confidence: 0.76,
            anchors: vec![schema::Anchor {
                kind: schema::AnchorKind::Inline,
                path: Some("src/ratio.rs".to_string()),
                line: Some(3),
                start_line: None,
                end_line: None,
                hunk_digest: Some("sha256:hunk-digest-example".to_string()),
            }],
            citations: vec!["citation-001".to_string()],
            suggested_fixes: vec!["fix-001".to_string()],
        }],
        comments: vec![schema::Comment {
            id: "comment-001".to_string(),
            kind: schema::CommentKind::Inline,
            intent: schema::CommentIntent::Finding,
            finding_id: Some("finding-001".to_string()),
            body: "Returning `0.0` for invalid input can be indistinguishable from a \
                   legitimate zero ratio. Consider an explicit error, `Option`, or \
                   documented sentinel behavior."
                .to_string(),
            anchor: schema::Anchor {
                kind: schema::AnchorKind::Inline,
                path: Some("src/ratio.rs".to_string()),
                line: Some(3),
                start_line: None,
                end_line: None,
                hunk_digest: None,
            },
            dedupe_key: Some("src/ratio.rs:3:zero-denominator".to_string()),
            suggested_fixes: vec!["fix-001".to_string()],
        }],
        suggested_fixes: vec![schema::SuggestedFix {
            id: "fix-001".to_string(),
            finding_id: Some("finding-001".to_string()),
            applicability: schema::FixApplicability::NeedsReview,
            format: schema::FixFormat::Replacement,
            edits: vec![schema::Edit {
                path: "src/ratio.rs".to_string(),
                start_line: 3,
                end_line: 3,
                replacement: Some(
                    "if denominator == 0.0 { return Err(RatioError::InvalidDenominator); }"
                        .to_string(),
                ),
            }],
            diff: None,
        }],
        citations: vec![schema::Citation {
            id: "citation-001".to_string(),
            kind: schema::CitationKind::Doc,
            title: Some("Ratio module invariants".to_string()),
            uri: Some("docs/ratio-invariants.md".to_string()),
            observed_at: Some("2026-07-03T00:00:00Z".to_string()),
            digest: Some("sha256:doc-digest-example".to_string()),
            excerpt: Some(
                "A zero ratio and an invalid ratio must remain distinguishable.".to_string(),
            ),
            used_by: vec!["finding-001".to_string()],
        }],
        receipts: vec![schema::Receipt {
            id: "receipt-master".to_string(),
            role: schema::ReceiptRole::Master,
            perspective: Some("correctness".to_string()),
            model: Some("openrouter/z-ai/glm-5.2".to_string()),
            provider: Some("openrouter".to_string()),
            harness: Some("opencode".to_string()),
            status: schema::ReceiptStatus::Completed,
            verdict: Some(schema::Verdict::Warn),
            summary: Some("Master reviewer produced one diff-grounded concern.".to_string()),
            artifact_digest: None,
            transcript_uri: Some("target/cerberus/transcript.txt".to_string()),
            usage: Some(schema::Usage {
                prompt_tokens: Some(4821),
                completion_tokens: Some(612),
                cost_usd: Some(0.0134),
            }),
            error: None,
        }],
        run: schema::RunInfo {
            engine_version: "cerberus-0.1.0".to_string(),
            config_digest: "sha256:config-digest-example".to_string(),
            started_at: "2026-07-03T00:00:00Z".to_string(),
            finished_at: "2026-07-03T00:00:04Z".to_string(),
            duration_ms: 4321,
            cost_usd: Some(0.0134),
            coverage: schema::Coverage {
                files_reviewed: vec!["src/ratio.rs".to_string()],
                files_with_findings: vec!["src/ratio.rs".to_string()],
            },
        },
        errors: vec![],
    };

    println!("{}", serde_json::to_string_pretty(&artifact).unwrap());
}
