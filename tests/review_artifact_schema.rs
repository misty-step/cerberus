//! Backlog 035: `cerberus.review_artifact.v1` has a committed JSON Schema
//! (`schemas/review-artifact.schema.json`) plus a canonical fixture
//! (`schemas/review-artifact.example.json`), both regenerated from the live
//! `ReviewArtifact` struct and its serializer -- never hand-maintained. A
//! `schema.rs` change that affects the artifact shape changes what these
//! tests compute, and fails here until the committed files are regenerated
//! and committed alongside the code change.

use cerberus::ReviewArtifact;

const SCHEMA_PATH: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/schemas/review-artifact.schema.json"
);
const FIXTURE_PATH: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/schemas/review-artifact.example.json"
);

fn committed_schema_json() -> serde_json::Value {
    let raw =
        std::fs::read_to_string(SCHEMA_PATH).expect("read schemas/review-artifact.schema.json");
    serde_json::from_str(&raw).expect("committed schema is valid JSON")
}

fn regenerated_schema_json() -> serde_json::Value {
    let schema = schemars::schema_for!(ReviewArtifact);
    serde_json::to_value(schema).unwrap()
}

#[test]
fn committed_schema_matches_the_live_struct() {
    let committed = committed_schema_json();
    let regenerated = regenerated_schema_json();
    assert_eq!(
        committed, regenerated,
        "schemas/review-artifact.schema.json is stale relative to the live ReviewArtifact \
         struct. Regenerate with:\n\n  cargo run --example gen_review_artifact_schema > schemas/review-artifact.schema.json\n\n\
         then review and commit the diff."
    );
}

#[test]
fn committed_fixture_round_trips_through_the_live_serializer() {
    let raw =
        std::fs::read_to_string(FIXTURE_PATH).expect("read schemas/review-artifact.example.json");
    let artifact: ReviewArtifact =
        serde_json::from_str(&raw).expect("committed fixture deserializes as ReviewArtifact");

    let mut re_serialized = serde_json::to_string_pretty(&artifact).unwrap();
    re_serialized.push('\n');

    assert_eq!(
        raw, re_serialized,
        "schemas/review-artifact.example.json does not match what the live serializer \
         produces for the same data (hand-edited, or stale relative to a schema.rs change). \
         Regenerate with:\n\n  cargo run --example gen_review_artifact_fixture > schemas/review-artifact.example.json\n\n\
         then review and commit the diff."
    );
}

#[test]
fn committed_fixture_validates_against_the_committed_schema() {
    let schema = committed_schema_json();
    let fixture_raw =
        std::fs::read_to_string(FIXTURE_PATH).expect("read schemas/review-artifact.example.json");
    let instance: serde_json::Value =
        serde_json::from_str(&fixture_raw).expect("fixture is valid JSON");

    let validator = jsonschema::validator_for(&schema).expect("committed schema compiles");
    let errors: Vec<String> = validator
        .iter_errors(&instance)
        .map(|error| format!("{error} at {}", error.instance_path()))
        .collect();

    assert!(
        errors.is_empty(),
        "canonical fixture does not validate against the committed schema:\n{}",
        errors.join("\n")
    );
}

// A negative control: a fabricated artifact missing a required field must be
// rejected. Without this, a schema that accidentally validates everything
// (e.g. an empty `{}` schema) would still pass the two tests above.
#[test]
fn schema_rejects_an_artifact_missing_a_required_field() {
    let schema = committed_schema_json();
    let mut instance =
        serde_json::from_str::<serde_json::Value>(&std::fs::read_to_string(FIXTURE_PATH).unwrap())
            .unwrap();
    instance
        .as_object_mut()
        .unwrap()
        .remove("verdict")
        .expect("fixture has a verdict field to remove");

    let validator = jsonschema::validator_for(&schema).expect("committed schema compiles");

    assert!(
        !validator.is_valid(&instance),
        "schema must reject an artifact missing the required 'verdict' field"
    );
}
