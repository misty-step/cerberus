# Verify citation & anchor resolution (cheap deterministic oracle)

Priority: P2 · Status: item 3 done; item 1 shipped warn-only 2026-07-02; item 2 still needs scoping · Estimate: S (item 2 is actually M+, see note)

## Goal
Reject confabulated or stale citations cheaply: every cited anchor/citation must resolve to real content — without Rust pretending to judge whether a finding is *faithful* (that's evals; see 015).

## Non-Goals
- No semantic-faithfulness enforcement (is the finding correct/useful) — that's a model + eval problem (015), not a Rust gate. Per ADR 0003.
- No new frozen taxonomy; `category` stays agent-free-form.

## Oracle
- [x] Inline/file anchor path is in the change (already enforced); extend to: the line number is in range for the cited file when the workspace is available (repo_head+). **Shipped warn-only 2026-07-02** — see the note below for why blocking behavior stayed a deferred decision while the warn half did not need to be.
- [ ] When an anchor carries `hunk_digest` or a citation carries `excerpt`/`digest`, it matches the actual bytes at that location; a fabricated/stale quote fails validation.
- [x] The substrate honors `policy.external_research`: web tools are not granted when `external_research == Forbid`, so granted capability matches the declared tier. **The ticket's "(dogfound, PR #466)" annotation was wrong/stale — PR #466 is "Deliver self-review tracer bullet, VISION, and groomed backlog," unrelated to webfetch gating. Live-checked `write_opencode_config` before touching it: `webfetch`/`websearch` were hardcoded to `"allow"` unconditionally, with no policy parameter at all — Forbid was a prompt instruction the model could ignore, not an actual permission boundary.** Fixed 2026-07-02: `write_opencode_config` now takes `external_research_allowed: bool` and sets `webfetch`/`websearch` to `"deny"` when `policy.external_research == Forbid`. New test `opencode_config_denies_web_tools_when_external_research_is_forbidden` pins it.
- [x] Every check *implemented so far* is a real oracle — removing the model, a non-AI process still decides pass/fail: the webfetch permission check (item 3) is a boolean policy comparison, and the line-range check (item 1) is an integer comparison against a file's real line count. No heuristic stands in for meaning. Item 2 (not yet implemented) will need the same discipline once it exists.

## Notes
**Why:** ADR 0003 + research (2026-06-23). The original 007 ("enforce groundedness in Rust") conflated *resolution* (a real oracle — keep, cheap, un-Goodhart-able) with *faithfulness* (no oracle — moved to evals/harness, 015). `validation.rs` already does the path-in-change check; this extends it to line/quote resolution, killing hallucinated citations for ~zero cost. Replaces the prior P0 "enforce groundedness" framing.

**2026-07-02 scoping note (first overnight pass) — why items 1-2 looked entirely blocked:**
Both looked like they required real filesystem access to the cited file's actual bytes
at *validation* time (`validate_artifact_for_request`), which is a pure function over
`&ReviewRequest`/`&ReviewArtifact` with zero filesystem I/O today. Threading a workspace
parameter through it would mean either changing a **public, `pub use` re-exported**
function signature (breaks every external caller), or a parallel entry point — a real
design decision, not a mechanical follow-up. Cerberus's own disposable tempdir is also
already dropped by the time validation runs (confirmed via `run_command_substrate`'s
`tempfile::Builder` going out of scope when the function returns, before `main.rs` ever
calls `validate_artifact_for_request`).

**2026-07-02 second pass, same night — found a safe half for item 1:** the premise above
was right for a *blocking* check, but wrong for a *warn-only* one. The review workspace
(`RunWorkspace`/`workspace.path()`) is still alive inside `run_command_substrate`, right
after the artifact is read back and before the tempdir drops — no signature change to
`validate_artifact_for_request` needed, because the check doesn't have to live there.
Shipped `harness::out_of_range_line_citation_warnings`: walks every inline anchor's cited
line number against the real file's line count in the still-live workspace, and prints a
non-blocking `warning:` line to stderr when it's out of range (silently skips when the
file can't be read at all — diff-only mode, where there is no real checkout to check
against, and a genuinely-missing-file case `validation.rs`'s path-in-change check already
owns). Live-verified: a real git-range review whose cited line exceeded the file's real
length printed the warning and still exited 0; `./scripts/verify.sh`'s own fixture (whose
`src/ratio.rs:3` citation is genuinely in-range for the 6-line file it commits) stays
silent. Scoped to `run_command_substrate` (opencode/omp) only — `container.rs`'s
archive-workspace path could reuse the same function (it also has a real, still-live
checkout at the point its artifact is read back) but wasn't wired in this pass, to keep
the diff focused; a natural, small follow-up.

**Item 2 is still genuinely blocked, unchanged from the first pass:**
`hunk_digest`/`excerpt`/`digest` have **no defined hashing/normalization convention
anywhere in the codebase today** (checked `schema.rs`, `prompt.rs`, `validation.rs`,
`docs/adr/`) — only a field name the model is told exists. Implementing "matches the
actual bytes" means inventing that convention from scratch (exact byte range, line
ending normalization, whitespace handling), which is a real design decision, not a
wire-up of an existing spec. Unlike item 1, there's no warn-only version that sidesteps
this — the convention has to exist before anything can be compared against it. Left for
explicit scoping.
