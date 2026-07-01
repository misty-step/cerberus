pub mod digest;
pub mod harness;
pub mod kernel;
pub mod mcp;
pub mod post;
pub mod prompt;
pub mod receipt;
pub mod render;
pub mod request;
pub mod schema;
mod secrets;
mod telemetry;
pub mod validation;

pub use digest::{request_digest, sha256_digest};
pub use harness::{
    FixtureSubstrateConfig, HarnessKind, OmpSubstrateConfig, OpenCodeSubstrateConfig,
};
pub use kernel::{ReviewKernel, ReviewRun, ReviewSubstrate, RunPolicy};
pub use post::{build_post_plan, GithubClient, PostPlan, SummaryTarget};
pub use receipt::{
    build_review_receipt_bundle, ReceiptBundleInput, ReceiptValidation, ReceiptValidationStatus,
    ReviewReceiptBundle, REVIEW_RECEIPT_BUNDLE_SCHEMA,
};
pub use render::render_markdown;
pub use schema::{
    ContextCapabilities, ReviewArtifact, ReviewRequest, ReviewTelemetry, REVIEW_ARTIFACT_SCHEMA,
};
pub use validation::{validate_artifact_for_request, validate_request};
