#![cfg(test)]

//! Shared `#[cfg(test)]` fixtures used across module test suites, so a
//! minimal `ReviewRequest` only needs to be defined once (backlog 011).
//! Individual suites override the fields they actually care about via
//! struct-update syntax rather than hand-rolling the whole literal again.

use crate::schema::{
    Change, ChangedFile, Diff, FileStatus, RequestContext, ReviewPolicy, ReviewRequest, Source,
    SourceKind, REVIEW_REQUEST_SCHEMA,
};

pub(crate) fn minimal_review_request() -> ReviewRequest {
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
