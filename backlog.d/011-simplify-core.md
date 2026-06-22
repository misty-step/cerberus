# Simplify and de-duplicate the core

Priority: P2 · Status: pending · Estimate: M

## Goal
Shrink the surface an editor must preserve: collapse a pass-through seam, de-duplicate display/test logic, and delete dead provenance — without changing the public `ReviewRequest.v1` / `ReviewArtifact.v1` / `ReviewKernel` seams.

## Oracle
- [ ] `kernel.rs` no longer rebuilds `ReviewRun` field-by-field from an identical `HarnessRun` (`kernel.rs:50-76`, `harness.rs:64-69`); the public `ReviewKernel::review -> ReviewRun` seam is preserved.
- [ ] `verdict_label` exists once (hoisted onto `schema::Verdict`), not duplicated at `render.rs:120-127` and `post.rs:434-441`.
- [ ] One shared `#[cfg(test)]` fixture builder replaces the ~5 hand-built request/artifact builders (`validation.rs:268`, `post.rs:654`, `receipt.rs:296`, `prompt.rs:356`, `harness.rs:1510`).
- [ ] Receipt "redaction" tests assert the positive allowed-field contract instead of the absence of strings the struct cannot hold (`receipt.rs:207-225`).

## Children
1. Collapse `HarnessRun`/`ReviewRun` duplication (return or alias) so `kernel.rs` is not a field-copy pass-through.
2. Hoist `verdict_label`/severity display onto `schema.rs`.
3. Single shared test-fixture helper (~150 LOC reclaimed).
4. Rewrite tautological receipt-redaction tests as positive-contract assertions.
5. (PROPOSED — humans ratify) DELETE the hardcoded `private_material_in_argv` constant (`harness.rs:106,192`); decide whether the other `ExecutionPlan` provenance fields are a documented JSON contract or dead surface.
6. (PROPOSED — needs spec ratification) Resolve the orphan `remote_runtime`/`RemoteTarget` surface (`schema.rs:106-110`) that has no producer path and an unreachable capability tier.

## Notes
**Why:** lane-arch F1-F6 (build green; all `path:line` cited). These advance VISION's "easy to change / operationally boring." F2 overlaps a real trust concern — the receipt-redaction tests give false confidence in a security-relevant claim because the struct has no field to redact (the strings are absent because never included, not because anything redacts). Deletions stay PROPOSED: the schema is LOCKED, so removing `remote_runtime` needs spec ratification, not a groom edit. Credit: `validation.rs`, `telemetry.rs`, `request.rs` parsing, and `post.rs` diff-line mapping are genuinely deep, well-designed modules — this is a surgical cleanup, not a rewrite.
