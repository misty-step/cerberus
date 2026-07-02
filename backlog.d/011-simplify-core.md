# Simplify and de-duplicate the core

Priority: P2 · Status: children 1-4 done (2026-07-02); 5-6 deferred, need human ratification · Estimate: M

## Goal
Shrink the surface an editor must preserve: collapse a pass-through seam, de-duplicate display/test logic, and delete dead provenance — without changing the public `ReviewRequest.v1` / `ReviewArtifact.v1` / `ReviewKernel` seams.

## Oracle
- [x] `kernel.rs` no longer rebuilds `ReviewRun` field-by-field inline; the public `ReviewKernel::review -> ReviewRun` seam is preserved. Added `ReviewRun::from_harness(HarnessRun, ReviewerPlanReceipt)` — the field copy now lives in one named, explicit place instead of an anonymous struct literal inside `review()`.
- [x] `verdict_label` exists once, hoisted onto `schema::Verdict::label()`; `render.rs` and `post.rs` both call it instead of each hand-rolling an identical match.
- [x] Shared `#[cfg(test)]` fixture builder — **scoped to the request builder, not artifact builders (see Children 3 note)**. New `src/test_support.rs::minimal_review_request()` replaces the three byte-for-byte-identical `ReviewRequest` literals in `validation.rs`, `receipt.rs`, `prompt.rs`.
- [x] Receipt "redaction" tests assert the positive allowed-field contract instead of the absence of strings the struct cannot hold. Both tests now call a shared `assert_receipt_bundle_field_allowlist` helper that fails if `ReviewReceiptBundle`'s serialized field set ever drifts from the known-safe allowlist — mutation-verified: added a hypothetical `leaked_transcript` field, confirmed both tests catch it, reverted.

## Children
1. **Done.** `ReviewRun::from_harness` in `kernel.rs`.
2. **Done.** `Verdict::label()` in `schema.rs`; `render.rs`/`post.rs` call sites updated, both local `verdict_label` fns deleted.
3. **Done, reduced scope.** Unified only the *request* builders (`validation.rs`, `receipt.rs`, `prompt.rs` were byte-for-byte identical or trivially so — verified no test in any of the three asserts on `.files` content or `diff.body` text before substituting). Left `post.rs`'s and `receipt.rs`'s/`prompt.rs`'s *artifact* builders and `harness.rs`'s JSON-macro-based `test_request()` alone: `post.rs`'s `request()` already delegates to a shared JSON fixture file (not hand-built), and the artifact builders differ meaningfully enough across files (different findings/comments/receipts shapes under test) that forcing one shared builder risked an over-parameterized, harder-to-read helper for a purely cosmetic LOC win. Reclaimed ~90 net lines, not the full ~150 estimated.
4. **Done.** `assert_receipt_bundle_field_allowlist` in `receipt.rs`'s test module.
5. **Deferred — needs human ratification**, unchanged from original scoping (PROPOSED deletion of `private_material_in_argv`).
6. **Deferred — needs spec ratification**, unchanged from original scoping (PROPOSED `remote_runtime`/`RemoteTarget` resolution).

## Notes
**Why:** lane-arch F1-F6 (build green; all `path:line` cited). These advance VISION's "easy to change / operationally boring." F2 overlaps a real trust concern — the receipt-redaction tests give false confidence in a security-relevant claim because the struct has no field to redact (the strings are absent because never included, not because anything redacts). Deletions stay PROPOSED: the schema is LOCKED, so removing `remote_runtime` needs spec ratification, not a groom edit. Credit: `validation.rs`, `telemetry.rs`, `request.rs` parsing, and `post.rs` diff-line mapping are genuinely deep, well-designed modules — this is a surgical cleanup, not a rewrite.
