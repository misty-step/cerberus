# Deepen the review kernel boundary

Priority: P1 | Status: shipped | Estimate: L

## Goal

Keep Cerberus easy to extend by separating the typed review kernel from CLI,
substrate adapter options, prompt schema prose, and request-source plumbing.

## Oracle

- [x] A typed `ReviewKernel::review(request, run_policy) -> ReviewRun` owns the
  common execution path.
- [x] OpenCode and OMP substrate options live behind adapter configs rather
  than leaking into the CLI and core harness interface.
- [x] Prompt schema instructions are generated from or checked against Rust
  schema/validation fixtures.
- [x] Adding a new request source or substrate does not require editing
  unrelated prompt or CLI code beyond registration.

## Verification System

- Claim: Cerberus has a deep review kernel with a small interface and
  substrate/source details behind adapters.
- Falsifier: adding a new substrate requires changing prompt schema prose;
  CLI flags leak into kernel structs; a schema change can compile while prompt
  fixtures still describe the old artifact shape.
- Driver: Rust tests for kernel API, prompt/schema golden tests, and a small
  fake substrate adapter.
- Grader: public API diff, compile-time type coverage, fixture output, and
  `./scripts/verify.sh`.
- Evidence packet: API docs or rustdoc snippet, prompt golden fixture, and
  adapter test output.
- Cadence: before adding a second production caller or new substrate.

## Children

1. Introduce `ReviewKernel`, `RunPolicy`, and `ReviewRun` types.
2. Move OpenCode/OMP-specific fields behind adapter config structs.
3. Add prompt/schema golden tests that fail when `ReviewArtifact.v1` contract
   prose drifts from Rust types.
4. Replace raw request metadata blobs with typed provenance where current
   callers need stable behavior.
5. Update CLI to become a thin caller of the kernel.

## Notes

**Why:** The architecture lane found the core idea is deep, but substrate knobs,
prompt schema instructions, and provenance strings still leak across module
boundaries. This matters before closed-loop delivery adds more callers and
projection paths.

**Shipped 2026-06-20:** Added `ReviewKernel`, `RunPolicy`, `ReviewRun`, and
typed `ReviewSubstrate` configs; moved CLI review/review-pr calls through the
kernel; added kernel integration coverage and prompt contract tests that compare
generated prompt field paths against a serialized Rust `ReviewArtifact` shape
plus validation fixture rules. Evidence: `./scripts/verify.sh`.
