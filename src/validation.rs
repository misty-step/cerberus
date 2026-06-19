use std::collections::{HashMap, HashSet};

use thiserror::Error;

use crate::digest::{request_digest, sha256_digest};
use crate::schema::{
    Anchor, AnchorKind, CitationKind, CommentKind, ContextCapabilities, ExternalResearchPolicy,
    ReviewArtifact, ReviewRequest, REVIEW_ARTIFACT_SCHEMA, REVIEW_REQUEST_SCHEMA,
};

#[derive(Debug, Error, PartialEq, Eq)]
pub enum ValidationError {
    #[error("unsupported request schema: {0}")]
    UnsupportedRequestSchema(String),
    #[error("unsupported artifact schema: {0}")]
    UnsupportedArtifactSchema(String),
    #[error("request id is required")]
    MissingRequestId,
    #[error("request change title is required")]
    MissingTitle,
    #[error("request diff body is required")]
    MissingDiff,
    #[error("unsupported diff format: {0}")]
    UnsupportedDiffFormat(String),
    #[error("diff digest mismatch: expected {expected}, got {actual}")]
    DiffDigestMismatch { expected: String, actual: String },
    #[error("artifact request id mismatch: expected {expected}, got {actual}")]
    RequestIdMismatch { expected: String, actual: String },
    #[error("artifact request digest mismatch: expected {expected}, got {actual}")]
    RequestDigestMismatch { expected: String, actual: String },
    #[error("artifact context capabilities overstate the request")]
    ContextCapabilityMismatch,
    #[error("inline anchor path is missing")]
    MissingInlinePath,
    #[error("inline anchor points outside changed files: {0}")]
    InlinePathOutsideChange(String),
    #[error("inline comment must use an inline anchor")]
    InlineCommentAnchorMismatch,
    #[error("finding is missing an evidence anchor: {0}")]
    FindingMissingAnchor(String),
    #[error("finding references unknown citation id: {0}")]
    UnknownCitation(String),
    #[error("citation {0} references unknown finding id {1}")]
    CitationReferencesUnknownFinding(String, String),
    #[error("url citation {0} is missing observed_at")]
    UrlCitationMissingObservedAt(String),
    #[error("external research requires citations for finding {0}")]
    ExternalResearchMissingCitation(String),
}

pub fn validate_request(request: &ReviewRequest) -> Result<(), ValidationError> {
    if request.schema_version != REVIEW_REQUEST_SCHEMA {
        return Err(ValidationError::UnsupportedRequestSchema(
            request.schema_version.clone(),
        ));
    }
    if request.request_id.trim().is_empty() {
        return Err(ValidationError::MissingRequestId);
    }
    if request.change.title.trim().is_empty() {
        return Err(ValidationError::MissingTitle);
    }
    if request.change.diff.format != "unified" {
        return Err(ValidationError::UnsupportedDiffFormat(
            request.change.diff.format.clone(),
        ));
    }
    if request.change.diff.body.trim().is_empty() {
        return Err(ValidationError::MissingDiff);
    }
    if let Some(actual) = &request.change.diff.digest {
        let expected = sha256_digest(request.change.diff.body.as_bytes());
        if *actual != expected {
            return Err(ValidationError::DiffDigestMismatch {
                expected,
                actual: actual.clone(),
            });
        }
    }
    Ok(())
}

pub fn validate_artifact_for_request(
    artifact: &ReviewArtifact,
    request: &ReviewRequest,
) -> Result<(), ValidationError> {
    if artifact.schema_version != REVIEW_ARTIFACT_SCHEMA {
        return Err(ValidationError::UnsupportedArtifactSchema(
            artifact.schema_version.clone(),
        ));
    }
    if artifact.request_id != request.request_id {
        return Err(ValidationError::RequestIdMismatch {
            expected: request.request_id.clone(),
            actual: artifact.request_id.clone(),
        });
    }
    let expected_digest =
        request_digest(request).map_err(|err| ValidationError::RequestDigestMismatch {
            expected: format!("serializable request ({err})"),
            actual: artifact.request_digest.clone(),
        })?;
    if artifact.request_digest != expected_digest {
        return Err(ValidationError::RequestDigestMismatch {
            expected: expected_digest,
            actual: artifact.request_digest.clone(),
        });
    }
    if artifact.context_capabilities != ContextCapabilities::from_request(request) {
        return Err(ValidationError::ContextCapabilityMismatch);
    }

    let changed_paths: HashSet<&str> = request
        .change
        .files
        .iter()
        .flat_map(|file| [Some(file.path.as_str()), file.old_path.as_deref()])
        .flatten()
        .collect();

    let finding_ids: HashSet<&str> = artifact
        .findings
        .iter()
        .map(|finding| finding.id.as_str())
        .collect();
    let citation_ids: HashSet<&str> = artifact
        .citations
        .iter()
        .map(|citation| citation.id.as_str())
        .collect();

    for finding in &artifact.findings {
        if finding.anchors.is_empty() {
            return Err(ValidationError::FindingMissingAnchor(finding.id.clone()));
        }
        for anchor in &finding.anchors {
            validate_anchor(anchor, &changed_paths)?;
        }
        for citation_id in &finding.citations {
            if !citation_ids.contains(citation_id.as_str()) {
                return Err(ValidationError::UnknownCitation(citation_id.clone()));
            }
        }
        if request.policy.external_research == ExternalResearchPolicy::RequireCitations
            && finding.citations.is_empty()
        {
            return Err(ValidationError::ExternalResearchMissingCitation(
                finding.id.clone(),
            ));
        }
    }

    for comment in &artifact.comments {
        if comment.kind == CommentKind::Inline && comment.anchor.kind != AnchorKind::Inline {
            return Err(ValidationError::InlineCommentAnchorMismatch);
        }
        validate_anchor(&comment.anchor, &changed_paths)?;
    }

    let citations_by_id: HashMap<&str, _> = artifact
        .citations
        .iter()
        .map(|citation| (citation.id.as_str(), citation))
        .collect();
    for (id, citation) in citations_by_id {
        if citation.kind == CitationKind::Url && citation.observed_at.is_none() {
            return Err(ValidationError::UrlCitationMissingObservedAt(
                id.to_string(),
            ));
        }
        for finding_id in &citation.used_by {
            if !finding_ids.contains(finding_id.as_str()) {
                return Err(ValidationError::CitationReferencesUnknownFinding(
                    id.to_string(),
                    finding_id.clone(),
                ));
            }
        }
    }

    Ok(())
}

fn validate_anchor(anchor: &Anchor, changed_paths: &HashSet<&str>) -> Result<(), ValidationError> {
    if anchor.kind != AnchorKind::Inline {
        return Ok(());
    }
    let path = anchor
        .path
        .as_deref()
        .ok_or(ValidationError::MissingInlinePath)?;
    if !changed_paths.contains(path) {
        return Err(ValidationError::InlinePathOutsideChange(path.to_string()));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::schema::*;

    fn request() -> ReviewRequest {
        ReviewRequest {
            schema_version: REVIEW_REQUEST_SCHEMA.to_string(),
            request_id: "req-1".to_string(),
            source: Source {
                kind: SourceKind::Fixture,
                external_id: None,
                repo: None,
                uri: None,
                metadata: serde_json::json!({}),
            },
            change: Change {
                title: "change".to_string(),
                description: None,
                base_ref: None,
                head_ref: None,
                head_sha: None,
                diff: Diff {
                    format: "unified".to_string(),
                    body: "diff --git a/src/lib.rs b/src/lib.rs\n".to_string(),
                    digest: None,
                },
                files: vec![ChangedFile {
                    path: "src/lib.rs".to_string(),
                    status: FileStatus::Modified,
                    old_path: None,
                    additions: Some(1),
                    deletions: Some(0),
                }],
            },
            context: RequestContext::default(),
            policy: ReviewPolicy::default(),
        }
    }

    fn artifact_for(request: &ReviewRequest) -> ReviewArtifact {
        ReviewArtifact {
            schema_version: REVIEW_ARTIFACT_SCHEMA.to_string(),
            artifact_id: "art-1".to_string(),
            request_id: request.request_id.clone(),
            request_digest: request_digest(request).unwrap(),
            lifecycle_state: LifecycleState::Completed,
            verdict: Verdict::Pass,
            context_capabilities: ContextCapabilities::from_request(request),
            summary: Summary {
                title: "clean".to_string(),
                body: "No blocking issues.".to_string(),
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
                started_at: "2026-06-19T00:00:00Z".to_string(),
                finished_at: "2026-06-19T00:00:01Z".to_string(),
                duration_ms: 1,
                cost_usd: None,
                coverage: Coverage {
                    files_reviewed: vec!["src/lib.rs".to_string()],
                    files_with_findings: Vec::new(),
                },
            },
            errors: Vec::new(),
        }
    }

    #[test]
    fn validates_matching_artifact() {
        let request = request();
        validate_request(&request).unwrap();
        validate_artifact_for_request(&artifact_for(&request), &request).unwrap();
    }

    #[test]
    fn rejects_wrong_request_digest() {
        let request = request();
        let mut artifact = artifact_for(&request);
        artifact.request_digest = "sha256:bad".to_string();
        assert!(matches!(
            validate_artifact_for_request(&artifact, &request),
            Err(ValidationError::RequestDigestMismatch { .. })
        ));
    }

    #[test]
    fn rejects_inline_anchor_outside_changed_files() {
        let request = request();
        let mut artifact = artifact_for(&request);
        artifact.findings.push(Finding {
            id: "f-1".to_string(),
            severity: Severity::Major,
            category: "correctness".to_string(),
            title: "bad path".to_string(),
            description: "points elsewhere".to_string(),
            evidence: "diff".to_string(),
            confidence: 0.9,
            anchors: vec![Anchor {
                kind: AnchorKind::Inline,
                path: Some("src/other.rs".to_string()),
                line: Some(1),
                start_line: None,
                end_line: None,
                hunk_digest: None,
            }],
            citations: Vec::new(),
            suggested_fixes: Vec::new(),
        });
        assert!(matches!(
            validate_artifact_for_request(&artifact, &request),
            Err(ValidationError::InlinePathOutsideChange(path)) if path == "src/other.rs"
        ));
    }

    #[test]
    fn rejects_unanchored_finding() {
        let request = request();
        let mut artifact = artifact_for(&request);
        artifact.findings.push(Finding {
            id: "f-1".to_string(),
            severity: Severity::Major,
            category: "correctness".to_string(),
            title: "unanchored".to_string(),
            description: "no anchor".to_string(),
            evidence: "unsupported".to_string(),
            confidence: 0.4,
            anchors: Vec::new(),
            citations: Vec::new(),
            suggested_fixes: Vec::new(),
        });
        assert!(matches!(
            validate_artifact_for_request(&artifact, &request),
            Err(ValidationError::FindingMissingAnchor(id)) if id == "f-1"
        ));
    }
}
