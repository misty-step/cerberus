use crate::schema::{ContextCapabilities, ReviewRequest};

pub const ARTIFACT_BEGIN: &str = "-----BEGIN CERBERUS_REVIEW_ARTIFACT_V1-----";
pub const ARTIFACT_END: &str = "-----END CERBERUS_REVIEW_ARTIFACT_V1-----";

pub fn build_master_prompt(
    request: &ReviewRequest,
    capabilities: &ContextCapabilities,
    request_digest: &str,
) -> Result<String, serde_json::Error> {
    let request_json = serde_json::to_string_pretty(request)?;
    let capabilities_json = serde_json::to_string_pretty(capabilities)?;
    let changed_paths: Vec<&str> = request
        .change
        .files
        .iter()
        .map(|file| file.path.as_str())
        .collect();
    let artifact_template = serde_json::to_string_pretty(&serde_json::json!({
        "schema_version": "cerberus.review_artifact.v1",
        "artifact_id": "artifact-unique-run-id",
        "request_id": request.request_id,
        "request_digest": request_digest,
        "lifecycle_state": "completed",
        "verdict": "PASS",
        "context_capabilities": capabilities,
        "summary": {
            "title": "Concise review title",
            "body": "Plain-language review result.",
            "analysis": "Evidence-backed analysis of the changed behavior and residual uncertainty.",
            "residual_risk": ["Unverified path, skipped command, or context limitation."]
        },
        "findings": [],
        "comments": [],
        "suggested_fixes": [],
        "citations": [],
        "receipts": [
            {
                "id": "receipt-master",
                "role": "master",
                "perspective": "synthesis",
                "model": null,
                "provider": null,
                "harness": "opencode",
                "status": "completed",
                "verdict": "PASS",
                "summary": "One-sentence receipt summary.",
                "artifact_digest": null,
                "transcript_uri": null,
                "usage": null,
                "error": null
            }
        ],
        "run": {
            "engine_version": "cerberus-opencode",
            "config_digest": "sha256:prompt-only",
            "started_at": "0",
            "finished_at": "0",
            "duration_ms": 0,
            "cost_usd": null,
            "coverage": {
                "files_reviewed": changed_paths,
                "files_with_findings": []
            }
        },
        "errors": []
    }))?;
    Ok(format!(
        r#"You are Cerberus, the master code reviewer.

Mission:
- Review only from the context actually available.
- You may dynamically launch subagents if the selected substrate supports doing so and it improves the review.
- Do not rely on predefined reviewer personas. Design any lane at runtime from the diff and context.
- If you launch a lane, give it explicit objective, scope, allowed context, system prompt, and output shape.
- Synthesize evidence into one durable ReviewArtifact.v1.
- Do not make architectural, runtime, security, or dependency claims without concrete evidence.
- External research is allowed only if the request policy permits it. External claims require citations.
- Blocking findings must cite concrete anchors.
- Produce exactly one artifact block and no second artifact block.
- Return only valid JSON inside the markers. No Markdown fences inside the artifact block.

Artifact block:
{begin}
{artifact_template}
{end}

Artifact requirements:
- Copy request_id, request_digest, and context_capabilities exactly from this prompt.
- Use lifecycle_state values: completed, completed_degraded, failed, skipped, cancelled, stale.
- Use verdict values: PASS, WARN, FAIL, SKIP.
- Empty findings/comments/suggested_fixes/citations arrays are valid when there are no actionable issues.
- If reporting a finding, include at least one anchor. Inline anchors must use a path from ReviewRequest.change.files.
- If reporting an inline comment, its anchor.kind must be inline.
- If external research is used, add citations and set observed_at for URL citations.
- Do not claim tests, runtime QA, base checkout inspection, or external research unless the request context actually provides it.

Request digest: {request_digest}

ContextCapabilities:
{capabilities_json}

ReviewRequest:
{request_json}
"#,
        begin = ARTIFACT_BEGIN,
        end = ARTIFACT_END,
        artifact_template = artifact_template,
        request_digest = request_digest,
        capabilities_json = capabilities_json,
        request_json = request_json
    ))
}
