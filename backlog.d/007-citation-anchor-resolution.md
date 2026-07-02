# Verify citation & anchor resolution (cheap deterministic oracle)

Priority: P2 · Status: item 3 fixed 2026-07-02 (was NOT already done, ticket's own claim was stale); items 1-2 need scoping · Estimate: S (items 1-2 are actually M+, see note)

## Goal
Reject confabulated or stale citations cheaply: every cited anchor/citation must resolve to real content — without Rust pretending to judge whether a finding is *faithful* (that's evals; see 015).

## Non-Goals
- No semantic-faithfulness enforcement (is the finding correct/useful) — that's a model + eval problem (015), not a Rust gate. Per ADR 0003.
- No new frozen taxonomy; `category` stays agent-free-form.

## Oracle
- [ ] Inline/file anchor path is in the change (already enforced); extend to: the line number is in range for the cited file when the workspace is available (repo_head+).
- [ ] When an anchor carries `hunk_digest` or a citation carries `excerpt`/`digest`, it matches the actual bytes at that location; a fabricated/stale quote fails validation.
- [x] The substrate honors `policy.external_research`: web tools are not granted when `external_research == Forbid`, so granted capability matches the declared tier. **The ticket's "(dogfound, PR #466)" annotation was wrong/stale — PR #466 is "Deliver self-review tracer bullet, VISION, and groomed backlog," unrelated to webfetch gating. Live-checked `write_opencode_config` before touching it: `webfetch`/`websearch` were hardcoded to `"allow"` unconditionally, with no policy parameter at all — Forbid was a prompt instruction the model could ignore, not an actual permission boundary.** Fixed 2026-07-02: `write_opencode_config` now takes `external_research_allowed: bool` and sets `webfetch`/`websearch` to `"deny"` when `policy.external_research == Forbid`. New test `opencode_config_denies_web_tools_when_external_research_is_forbidden` pins it.
- [ ] Every check is a real oracle — removing the model, a non-AI process still decides pass/fail. No heuristic stands in for meaning.

## Notes
**Why:** ADR 0003 + research (2026-06-23). The original 007 ("enforce groundedness in Rust") conflated *resolution* (a real oracle — keep, cheap, un-Goodhart-able) with *faithfulness* (no oracle — moved to evals/harness, 015). `validation.rs` already does the path-in-change check; this extends it to line/quote resolution, killing hallucinated citations for ~zero cost. Replaces the prior P0 "enforce groundedness" framing.

**2026-07-02 scoping note (overnight pass) — why items 1-2 are unstarted, not attempted:**
Both require real filesystem access to the cited file's actual bytes at validation
time, and that's a bigger, more design-heavy change than the "S" estimate suggests:
- `validate_artifact_for_request` is a pure function over `&ReviewRequest`/
  `&ReviewArtifact` today — zero filesystem I/O. Adding it means either
  threading an `Option<&Path>` workspace parameter through a **public, `pub use`
  re-exported** function signature (breaks every external caller, not just this
  repo's own `main.rs`/`mcp.rs` call sites), or a parallel `validate_*_with_workspace`
  entry point.
- The workspace path that would need to stay live is `request.context.workspaces.head.path`
  — the *caller-supplied* checkout, not Cerberus's own disposable tempdir (that one is
  already dropped by the time validation runs, confirmed by reading `run_command_substrate`:
  its `tempfile::Builder::new().tempdir()` goes out of scope and deletes itself when the
  function returns, before `main.rs` ever calls `validate_artifact_for_request`). Whether
  the caller-supplied path is guaranteed to still exist/be unchanged at validation time
  for every caller (`review`, `review-diff`, `review-pr`, MCP) needs a decision, not an
  assumption.
- `hunk_digest`/`excerpt`/`digest` have **no defined hashing/normalization convention
  anywhere in the codebase today** (checked `schema.rs`, `prompt.rs`, `validation.rs`,
  `docs/adr/`) — only a field name the model is told exists. Implementing "matches the
  actual bytes" means inventing that convention from scratch (exact byte range, line
  ending normalization, whitespace handling), which is a real design decision, not a
  wire-up of an existing spec.

Per the overnight contract's "skip operator-decision items, note them" rule. A future
pass should scope: (a) whether `validate_artifact_for_request`'s public signature may
change, (b) the hunk_digest/excerpt hashing convention, (c) fail-open vs fail-closed
when the workspace path is stale/missing at validation time.
