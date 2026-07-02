//! Regenerates `schemas/review-artifact.schema.json` from the live
//! `ReviewArtifact` struct (backlog 035). Run:
//!
//!   cargo run --example gen_review_artifact_schema > schemas/review-artifact.schema.json
//!
//! `tests/review_artifact_schema.rs` fails if the committed file drifts from
//! what this prints, so a schema.rs change that affects the artifact shape
//! forces a conscious regeneration + commit of the schema file.

fn main() {
    let schema = schemars::schema_for!(cerberus::ReviewArtifact);
    println!("{}", serde_json::to_string_pretty(&schema).unwrap());
}
