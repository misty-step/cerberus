use crate::schema::{Anchor, ReviewArtifact, Severity};

pub fn render_markdown(artifact: &ReviewArtifact) -> String {
    let mut out = String::new();
    out.push_str(&format!(
        "# Cerberus Review: {}\n\n",
        artifact.verdict.label()
    ));
    out.push_str(&format!("**Artifact:** `{}`  \n", artifact.artifact_id));
    out.push_str(&format!("**Request:** `{}`  \n", artifact.request_id));
    out.push_str(&format!(
        "**Lifecycle:** `{:?}`  \n",
        artifact.lifecycle_state
    ));
    out.push_str(&format!(
        "**Duration:** `{}ms`  \n",
        artifact.run.duration_ms
    ));
    match artifact.run.cost_usd {
        Some(cost) => out.push_str(&format!("**Cost:** `${cost:.4}`\n\n")),
        None => out.push_str("**Cost:** `unknown`\n\n"),
    }

    out.push_str("## Summary\n\n");
    out.push_str(&format!("**{}**\n\n", artifact.summary.title));
    out.push_str(&artifact.summary.body);
    out.push_str("\n\n");
    if !artifact.summary.analysis.trim().is_empty() {
        out.push_str("### Analysis\n\n");
        out.push_str(&artifact.summary.analysis);
        out.push_str("\n\n");
    }

    out.push_str("## Context Capabilities\n\n");
    out.push_str(&format!(
        "- diff: `{}`\n- repo_head: `{}`\n- repo_base: `{}`\n- local_runtime: `{}`\n- remote_runtime: `{}`\n- external_research: `{:?}`\n\n",
        artifact.context_capabilities.diff,
        artifact.context_capabilities.repo_head,
        artifact.context_capabilities.repo_base,
        artifact.context_capabilities.local_runtime,
        artifact.context_capabilities.remote_runtime,
        artifact.context_capabilities.external_research
    ));

    out.push_str("## Coverage\n\n");
    if artifact.run.coverage.files_reviewed.is_empty() {
        out.push_str("No files recorded as reviewed.\n\n");
    } else {
        out.push_str(&format!(
            "**Files reviewed ({}):** {}\n\n",
            artifact.run.coverage.files_reviewed.len(),
            artifact
                .run
                .coverage
                .files_reviewed
                .iter()
                .map(|path| format!("`{path}`"))
                .collect::<Vec<_>>()
                .join(", ")
        ));
    }
    if !artifact.run.coverage.files_with_findings.is_empty() {
        out.push_str(&format!(
            "**Files with findings:** {}\n\n",
            artifact
                .run
                .coverage
                .files_with_findings
                .iter()
                .map(|path| format!("`{path}`"))
                .collect::<Vec<_>>()
                .join(", ")
        ));
    }

    out.push_str("## Findings\n\n");
    if artifact.findings.is_empty() {
        out.push_str("No findings.\n\n");
    } else {
        for finding in &artifact.findings {
            out.push_str(&format!(
                "### [{}] {}\n\n",
                severity_label(&finding.severity),
                finding.title
            ));
            out.push_str(&format!("**Category:** `{}`  \n", finding.category));
            out.push_str(&format!("**Confidence:** `{:.2}`  \n", finding.confidence));
            if !finding.anchors.is_empty() {
                let anchors = finding
                    .anchors
                    .iter()
                    .map(anchor_label)
                    .collect::<Vec<_>>()
                    .join(", ");
                out.push_str(&format!("**Anchors:** {}  \n", anchors));
            }
            out.push('\n');
            out.push_str(&finding.description);
            out.push_str("\n\n");
            out.push_str(&format!("Evidence: {}\n\n", finding.evidence));
        }
    }

    if !artifact.comments.is_empty() {
        out.push_str("## Comments\n\n");
        for comment in &artifact.comments {
            out.push_str(&format!(
                "- `{}` {}: {}\n",
                comment.id,
                anchor_label(&comment.anchor),
                comment.body
            ));
        }
        out.push('\n');
    }

    if !artifact.citations.is_empty() {
        out.push_str("## Citations\n\n");
        for citation in &artifact.citations {
            let title = citation.title.as_deref().unwrap_or(&citation.id);
            if let Some(uri) = &citation.uri {
                out.push_str(&format!("- [{}]({})", title, uri));
            } else {
                out.push_str(&format!("- {}", title));
            }
            if let Some(observed_at) = &citation.observed_at {
                out.push_str(&format!(" observed `{}`", observed_at));
            }
            out.push('\n');
        }
        out.push('\n');
    }

    if !artifact.summary.residual_risk.is_empty() {
        out.push_str("## Residual Risk\n\n");
        for risk in &artifact.summary.residual_risk {
            out.push_str(&format!("- {}\n", risk));
        }
        out.push('\n');
    }

    out.push_str("## Receipts\n\n");
    if artifact.receipts.is_empty() {
        out.push_str("No lane receipts recorded.\n");
    } else {
        for receipt in &artifact.receipts {
            out.push_str(&format!(
                "- `{}` {:?} via `{}`: {:?}\n",
                receipt.id,
                receipt.role,
                receipt.harness.as_deref().unwrap_or("unknown"),
                receipt.status
            ));
        }
    }
    out
}

fn severity_label(severity: &Severity) -> &'static str {
    match severity {
        Severity::Info => "info",
        Severity::Minor => "minor",
        Severity::Major => "major",
        Severity::Critical => "critical",
    }
}

fn anchor_label(anchor: &Anchor) -> String {
    let path = anchor.path.as_deref().unwrap_or("<run>");
    if let Some(line) = anchor.line {
        format!("{}:{}", path, line)
    } else if let (Some(start), Some(end)) = (anchor.start_line, anchor.end_line) {
        format!("{}:{}-{}", path, start, end)
    } else {
        path.to_string()
    }
}

#[cfg(test)]
mod tests {
    use crate::schema::*;

    use super::render_markdown;

    #[test]
    fn renders_empty_findings() {
        let artifact = ReviewArtifact {
            schema_version: REVIEW_ARTIFACT_SCHEMA.to_string(),
            artifact_id: "a".to_string(),
            request_id: "r".to_string(),
            request_digest: "sha256:r".to_string(),
            lifecycle_state: LifecycleState::Completed,
            verdict: Verdict::Pass,
            context_capabilities: ContextCapabilities {
                diff: true,
                repo_head: false,
                repo_base: false,
                local_runtime: false,
                remote_runtime: false,
                external_research: ExternalResearchPolicy::Forbid,
            },
            summary: Summary {
                title: "Clean".to_string(),
                body: "No issues.".to_string(),
                analysis: String::new(),
                residual_risk: Vec::new(),
            },
            findings: Vec::new(),
            comments: Vec::new(),
            suggested_fixes: Vec::new(),
            citations: Vec::new(),
            receipts: Vec::new(),
            run: RunInfo {
                engine_version: "test".to_string(),
                config_digest: "sha256:test".to_string(),
                started_at: "0".to_string(),
                finished_at: "1".to_string(),
                duration_ms: 1,
                cost_usd: None,
                coverage: Coverage {
                    files_reviewed: Vec::new(),
                    files_with_findings: Vec::new(),
                },
            },
            errors: Vec::new(),
        };
        let markdown = render_markdown(&artifact);
        assert!(markdown.contains("# Cerberus Review: PASS"));
        assert!(markdown.contains("No findings."));
    }

    fn artifact_with_run(run: RunInfo) -> ReviewArtifact {
        ReviewArtifact {
            schema_version: REVIEW_ARTIFACT_SCHEMA.to_string(),
            artifact_id: "a".to_string(),
            request_id: "r".to_string(),
            request_digest: "sha256:r".to_string(),
            lifecycle_state: LifecycleState::Completed,
            verdict: Verdict::Pass,
            context_capabilities: ContextCapabilities {
                diff: true,
                repo_head: false,
                repo_base: false,
                local_runtime: false,
                remote_runtime: false,
                external_research: ExternalResearchPolicy::Forbid,
            },
            summary: Summary {
                title: "Clean".to_string(),
                body: "No issues.".to_string(),
                analysis: String::new(),
                residual_risk: Vec::new(),
            },
            findings: Vec::new(),
            comments: Vec::new(),
            suggested_fixes: Vec::new(),
            citations: Vec::new(),
            receipts: Vec::new(),
            run,
            errors: Vec::new(),
        }
    }

    // Pins the VISION promise "operators can see ... the time/cost it took":
    // this data lived in the schema but was previously rendered only inside
    // a #[cfg(test)] block, never in the production Markdown callers/GitHub
    // actually see (backlog 009).
    #[test]
    fn renders_duration_and_cost_in_production_markdown() {
        let artifact = artifact_with_run(RunInfo {
            engine_version: "test".to_string(),
            config_digest: "sha256:test".to_string(),
            started_at: "0".to_string(),
            finished_at: "1".to_string(),
            duration_ms: 4321,
            cost_usd: Some(0.0042),
            coverage: Coverage {
                files_reviewed: Vec::new(),
                files_with_findings: Vec::new(),
            },
        });

        let markdown = render_markdown(&artifact);

        assert!(markdown.contains("**Duration:** `4321ms`"));
        assert!(markdown.contains("**Cost:** `$0.0042`"));
    }

    #[test]
    fn renders_unknown_cost_when_the_substrate_did_not_report_one() {
        let artifact = artifact_with_run(RunInfo {
            engine_version: "test".to_string(),
            config_digest: "sha256:test".to_string(),
            started_at: "0".to_string(),
            finished_at: "1".to_string(),
            duration_ms: 1,
            cost_usd: None,
            coverage: Coverage {
                files_reviewed: Vec::new(),
                files_with_findings: Vec::new(),
            },
        });

        let markdown = render_markdown(&artifact);

        assert!(markdown.contains("**Cost:** `unknown`"));
    }

    #[test]
    fn renders_coverage_files_reviewed_and_with_findings() {
        let artifact = artifact_with_run(RunInfo {
            engine_version: "test".to_string(),
            config_digest: "sha256:test".to_string(),
            started_at: "0".to_string(),
            finished_at: "1".to_string(),
            duration_ms: 1,
            cost_usd: None,
            coverage: Coverage {
                files_reviewed: vec!["src/lib.rs".to_string(), "src/main.rs".to_string()],
                files_with_findings: vec!["src/main.rs".to_string()],
            },
        });

        let markdown = render_markdown(&artifact);

        assert!(markdown.contains("**Files reviewed (2):**"));
        assert!(markdown.contains("`src/lib.rs`"));
        assert!(markdown.contains("**Files with findings:** `src/main.rs`"));
    }

    #[test]
    fn renders_no_files_reviewed_when_coverage_is_empty() {
        let artifact = artifact_with_run(RunInfo {
            engine_version: "test".to_string(),
            config_digest: "sha256:test".to_string(),
            started_at: "0".to_string(),
            finished_at: "1".to_string(),
            duration_ms: 1,
            cost_usd: None,
            coverage: Coverage {
                files_reviewed: Vec::new(),
                files_with_findings: Vec::new(),
            },
        });

        let markdown = render_markdown(&artifact);

        assert!(markdown.contains("No files recorded as reviewed."));
    }
}
