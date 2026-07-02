# Commit a versioned JSON schema + canonical fixture for the review artifact

Priority: P1 · Status: ready · Estimate: M

## Goal
`cerberus.review_artifact.v1` exists as a committed JSON Schema plus a canonical generated fixture, so downstream consumers (crucible mirrors the structs by hand today) have a machine-checkable contract instead of a doc-comment pointer.

## Oracle
- [ ] A JSON Schema file for the review artifact (Finding/Anchor/Severity from `src/schema.rs:290-332`) is committed under a schemas/ or contracts/ path.
- [ ] A test generates a canonical fixture from the live serializer and validates it against the schema; changing `schema.rs` incompatibly fails this test.
- [ ] The fixture is the documented regeneration source for crucible's `crucible-core/tests/fixtures/cerberus-artifact.json` (README note or script).

## Notes
Additive only — no changes to the artifact shape itself. Crucible's mirror (`crucible-core/src/artifact.rs:16-109`, "Source of truth: cerberus/src/schema.rs") stays as-is tonight; a crucible-side conformance test is its own ticket. Do NOT touch the write-only producer-manifest code (`src/producer.rs:79-130`) — its deletion is a proposal for the operator, not overnight work.
**Why:** 2026-07-01 composition seam audit, Seam 1 — ranked #2 most-likely-to-break; cerberus devs currently get zero signal that crucible depends on this shape, and `schema_version` is unvalidated downstream.
