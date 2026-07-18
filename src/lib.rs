pub mod container;
pub mod digest;
pub mod harness;
pub mod kernel;
pub mod mcp;
pub mod openrouter_keys;
pub mod orchestration;
pub mod post;
pub mod producer;
pub mod prompt;
pub mod receipt;
pub mod render;
pub mod request;
pub mod schema;
pub mod seat_policy;
mod secrets;
mod telemetry;
#[cfg(test)]
mod test_support;
pub mod validation;

pub use container::{
    ContainerOpencodeSubstrateConfig, DEFAULT_CONTAINER_IMAGE, DEFAULT_EGRESS_ALLOW_HOST,
};
pub use digest::{request_digest, sha256_digest};
pub use harness::{
    FixtureSubstrateConfig, HarnessKind, OmpSubstrateConfig, OpenCodeSubstrateConfig,
};
pub use kernel::{ReviewKernel, ReviewRun, ReviewSubstrate, RunPolicy};
pub use openrouter_keys::{
    mint_review_key, scoped_key_name, sweep_orphaned_keys, KeyRecord, MintedKey,
    ProvisioningClient, ScopedKeyGuard, DEFAULT_BASE_URL as OPENROUTER_PROVISIONING_BASE_URL,
    REVIEW_KEY_NAME_PREFIX,
};
pub use orchestration::{
    build_reviewer_plan, launch_planned_child_lanes, synthesize_lane_receipts_into_artifact,
    ReviewerLaneLaunch, ReviewerLaneReceipt, ReviewerLaneSubstrate, ReviewerPlanReceipt,
    REVIEWER_LANE_RECEIPT_SCHEMA, REVIEWER_PLAN_SCHEMA,
};
pub use post::{build_post_plan, GithubClient, PostPlan, SummaryTarget};
pub use producer::{
    build_crucible_producer_manifest, CrucibleProducerManifest, CrucibleProducerManifestInput,
    CRUCIBLE_PRODUCER_MANIFEST_SCHEMA,
};
pub use receipt::{
    build_review_receipt_bundle, ReceiptBundleInput, ReceiptValidation, ReceiptValidationStatus,
    ReviewReceiptBundle, REVIEW_RECEIPT_BUNDLE_SCHEMA,
};
pub use render::render_markdown;
pub use schema::{
    ContextCapabilities, ReviewArtifact, ReviewRequest, ReviewTelemetry, REVIEW_ARTIFACT_SCHEMA,
};
pub use seat_policy::{
    admit_seat_plan, classify_diff_tier, load_seat_policy, DiffTier, RequiredSeat,
    SeatAdmissionVerdict, SeatDimension, SeatPolicy, Tier1Floor, SEAT_POLICY_SCHEMA,
};
pub use validation::{validate_artifact_for_request, validate_request};
