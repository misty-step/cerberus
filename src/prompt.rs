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

Artifact block:
{begin}
{{ valid JSON ReviewArtifact.v1 }}
{end}

Request digest: {request_digest}

ContextCapabilities:
{capabilities_json}

ReviewRequest:
{request_json}
"#,
        begin = ARTIFACT_BEGIN,
        end = ARTIFACT_END,
        request_digest = request_digest,
        capabilities_json = capabilities_json,
        request_json = request_json
    ))
}
