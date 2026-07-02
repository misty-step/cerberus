# Commit a versioned JSON schema + canonical fixture for the review artifact

Priority: P1 · Status: done (2026-07-03) · Estimate: M

## Goal
`cerberus.review_artifact.v1` exists as a committed JSON Schema plus a canonical generated fixture, so downstream consumers (crucible mirrors the structs by hand today) have a machine-checkable contract instead of a doc-comment pointer.

## Oracle
- [x] A JSON Schema file for the review artifact is committed under `schemas/`
      (`schemas/review-artifact.schema.json`) — auto-derived from the live
      struct graph via `schemars::JsonSchema` on all 27 types reachable from
      `ReviewArtifact` (added the derive to each; zero hand-written schema).
- [x] `tests/review_artifact_schema.rs` (4 tests) generates the schema and a
      canonical fixture from the live serializer and validates the fixture
      against the schema; changing `schema.rs` incompatibly fails this test.
      Mutation-verified: added a field to `ReviewArtifact` without
      regenerating the committed files, confirmed
      `committed_schema_matches_the_live_struct` fails with regen
      instructions, reverted. A negative-control test also confirms the
      schema genuinely rejects a fixture missing a required field (guards
      against an accidentally-permissive `{}` schema silently passing).
- [x] The fixture (`schemas/review-artifact.example.json`) is documented as
      the regeneration source for crucible's
      `crucible-core/tests/fixtures/cerberus-artifact.json` — new "Artifact
      schema contract" section in README.md.

## Notes
Additive only — no changes to the artifact shape itself. Crucible's mirror (`crucible-core/src/artifact.rs:16-109`, "Source of truth: cerberus/src/schema.rs") stays as-is tonight; a crucible-side conformance test is its own ticket. Do NOT touch the write-only producer-manifest code (`src/producer.rs:79-130`) — its deletion is a proposal for the operator, not overnight work.
**Why:** 2026-07-01 composition seam audit, Seam 1 — ranked #2 most-likely-to-break; cerberus devs currently get zero signal that crucible depends on this shape, and `schema_version` is unvalidated downstream.

**Implementation note (2026-07-03):** added `schemars` (regular dependency,
derives the schema from the live struct — no hand-maintained schema to drift)
and `jsonschema` (dev-dependency, `default-features = false` to skip the
reqwest/tokio/aws-lc-rs HTTP-$ref-resolution stack the default features pull
in — we only validate a local, self-contained schema against a local
fixture, no network resolution needed). Two new example binaries
(`examples/gen_review_artifact_schema.rs`, `gen_review_artifact_fixture.rs`)
are the regeneration commands, documented in README.md.
