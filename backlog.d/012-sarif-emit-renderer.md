# Add an optional emit-only SARIF renderer (post-MVP)

Priority: P3 · Status: pending · Estimate: M

## Goal
Let callers project a `ReviewArtifact.v1` to SARIF 2.1.0 for GitHub code-scanning interop — as a lossy downstream renderer only, never as the artifact and never as an ingest path.

## Oracle
- [ ] `cerberus render --artifact … --sarif <file>` emits valid SARIF 2.1.0 carrying findings + locations + `partialFingerprints`.
- [ ] The verdict / summary / lifecycle / provenance / receipt that SARIF cannot represent stay in `ReviewArtifact.v1`; SARIF is documented as lossy.
- [ ] No SARIF *ingest* path is added (explicit non-goal).

## Notes
**Why:** lane-exemplars #2 + verdict 1. SARIF is structurally incapable of holding Cerberus's run-level verdict, free-text summary, lifecycle, request provenance, or receipts, so it can only be a downstream projection — exactly where `spec.md` Post-MVP already files "SARIF/check renderers." Emitting buys the GitHub code-scanning UI + free cross-run dedup via `partialFingerprints`. Ingesting SARIF is a non-goal trap: it pulls Cerberus toward linter-aggregation (the 40+ scanner game) and dilutes the one-master-reviewer rule. Low priority; captured for completeness of the interop story. Relates to ticket 007 child 5 (finding fingerprints for idempotent posting borrow SARIF's `partialFingerprints` semantics even though we reject SARIF as the artifact).
