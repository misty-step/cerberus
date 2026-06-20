pub mod digest;
pub mod harness;
pub mod kernel;
pub mod post;
pub mod prompt;
pub mod render;
pub mod request;
pub mod schema;
pub mod validation;

pub use digest::{request_digest, sha256_digest};
pub use harness::{
    extract_marked_artifact, FixtureSubstrateConfig, HarnessKind, OmpSubstrateConfig,
    OpenCodeSubstrateConfig,
};
pub use kernel::{ReviewKernel, ReviewRun, ReviewSubstrate, RunPolicy};
pub use post::{build_post_plan, GithubClient, PostPlan, SummaryTarget};
pub use render::render_markdown;
pub use schema::{ContextCapabilities, ReviewArtifact, ReviewRequest, REVIEW_ARTIFACT_SCHEMA};
pub use validation::{validate_artifact_for_request, validate_request};
