# Reliable review emission: emit to a file, validate, re-ask

Priority: P1 · Status: shipped · Estimate: M · Shape: docs/plans/016-review-emission.html

**Shipped 2026-06-24 (PR #476):** file emission (`<workspace>/review-artifact.json`) + a bounded, fail-closed validate-and-re-ask loop; deleted the marker/XML/raw parser and the ~1800-char prompt lecture; no new dependency. Live dogfood (real OpenCode, `openrouter/z-ai/glm-4.6`) recovered a missing first emission via the re-ask. Evidence: `./scripts/verify.sh` + `target/cerberus/dogfood/`.

## Goal
Make the agent reliably yield a valid `ReviewArtifact.v1` by writing it to a file with its existing tools and having Cerberus validate-and-re-ask on failure — deleting the fragile marker/XML/raw parser and the ~1800-char prompt lecture, with no new dependency.

## Non-Goals
- The caller-neutral artifact CONTRACT stays; only emission changes.
- No custom MCP / `response_format` (research: overkill / OpenCode can't).
- No GitHub-writing tool for the agent; Cerberus keeps posting via `post.rs`.
- No multi-destination adapter framework yet (rule of three — one GitHub adapter is enough).
- Not about faithfulness/quality (that is 015); this is valid *structure*, reliably.

## Oracle
- [ ] A malformed-then-corrected emission fixture (invalid on attempt 1, valid on attempt 2) makes the review succeed only via the re-ask, and the transcript shows the exact validation error was carried back.
- [ ] `rg 'extract_marked_artifact|ARTIFACT_BEGIN|extract_unmarked_artifact_json' src/` has no production hits.
- [ ] `./scripts/verify.sh` green (fixture + OMP paths moved to file emission); `git diff Cargo.toml` shows no new dependency.
- [ ] The re-ask loop is bounded (≤2 retries) and fail-closed — never silently accepts an invalid artifact.
- [ ] Live dogfood: one `review-pr --post` produces a valid posted artifact with the parser deleted; a recovered retry shows in the transcript if the first emission was invalid.

## Verification System
- Claim: file emission + a bounded validate-and-re-ask loop reliably yields a valid artifact, parser deleted, no new dep.
- Falsifier: invalid first emission silently accepted; re-ask omits the real error; verify.sh regresses; a new dep appears; the agent can reach GitHub directly.
- Driver: the malformed-then-corrected fixture through the review path + one real `review-pr` dogfood.
- Grader: fixture succeeds only via retry; `rg` shows the parser gone; verify.sh exit 0; dogfood posts a valid artifact.
- Evidence packet: fixture + transcript (carried error); dogfood artifact/receipt under `target/cerberus/`.
- Cadence: fixture in verify.sh always; dogfood on prompt/emission change.
- Gaps/waiver: faithfulness is 015; OpenCode `--session` reliability is spiked in M2 with a fallback.

## Children
1. **M1 emit + delete parser:** slim `build_opencode_message` (prompt.rs) to "write your `ReviewArtifact.v1` JSON to `<out-path>`"; harness reads + `serde`-parses the file; delete `extract_marked_artifact`/`extract_opencode_text_events`/`extract_json_between_markers`/`extract_unmarked_artifact_json` (harness.rs:969–1090) + `ARTIFACT_BEGIN/END`; move the fixture + OMP paths to file emission and update their tests.
2. **M2 validate-and-re-ask:** move `validate_artifact_for_request` into the run loop (today post-hoc, main.rs:365/447); capture the OpenCode `sessionID`; on miss/invalid, `opencode run --session <id> "<error>: fix and rewrite <out-path>"`, ≤2 retries, fail-closed. The loop lives where request + harness + validator meet.

## Notes
**Why:** the third and simplest convergence (structured output → custom MCP → this), driven by the operator's "do we build our own or stitch existing tools?" + research. Mature reviewers produce-then-post and treat the host as a dumb sink; the neutral artifact is a thin typed data object (Fowler YAGNI exemption) that gives the idempotency/validation direct-posters had to rebuild. The custom MCP and write-a-file terminate at the same validator, so MCP is overkill for one agent we control; the reliability comes from validate-and-re-ask (~80% first retry, >99% by the second). Per ADR 0003: contract/validation deterministic; emission reliability is harness engineering. Full design, alternatives, milestones, risks in the linked HTML plan.
