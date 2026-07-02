# Build a diff-shape fixture corpus for request-building robustness

Priority: P3 · Status: done (2026-07-02) · Estimate: M

## Goal
`src/request.rs` has 11 unit tests covering individual parsing branches
(rename, missing binary, empty diff) but no single fixture corpus exercises
`build_git_range_request` end-to-end across the diff shapes most likely to
break a review request builder: a file mode change (executable bit flip), a
pure delete (no additions), and a single file with many separated hunks. This
is deterministic request-building coverage only — NOT review-quality/
LLM-faithfulness evals, which stay in Crucible/Daedalus per ADR 0003.

## Oracle
- [x] Fixture corpus in `src/request.rs`'s `#[cfg(test)]` module, three cases,
      each building a real temp git repo and running `build_git_range_request`
      end-to-end (empirically verified the exact git output for each shape
      via manual `git diff` runs before writing assertions, rather than
      guessing):
      - `build_git_range_request_handles_an_executable_bit_only_mode_change`
        (`#[cfg(unix)]` — uses `PermissionsExt::set_mode`)
      - `build_git_range_request_handles_a_pure_file_delete`
      - `build_git_range_request_handles_a_file_with_three_separated_hunks`
- [x] Each case calls `crate::validation::validate_request` (the real oracle,
      not a schema_version string comparison — `build_git_range_request`
      always sets that field correctly by construction, so a string check
      would be tautological) and asserts `ChangedFile`/`Diff` fields match
      real git behavior for that shape: mode-change is `Modified` with
      `(Some(0), Some(0))` additions/deletions (no content changed) and a
      diff body carrying `old mode`/`new mode`; pure delete is `Removed`
      with `(Some(0), Some(3))` for a 3-line file; the multi-hunk case is
      `Modified` with `(Some(3), Some(3))` and >=3 `@@` hunk markers in the
      diff body.
- [x] Shared doc comment above the three cases names the corpus's purpose;
      extracted a `build_range_request_for_test` helper (also now used by
      038's binary-file test) to keep each case focused on its own shape
      rather than repeating `GitRangeRequestOptions` boilerplate.
- [x] `./scripts/verify.sh` green.

## Notes
Scope explicitly excludes: LLM finding quality, golden "expected findings" —
that is Daedalus/Crucible territory per VISION.md and ADR 0003, not a Rust
oracle. This ticket is purely "does the deterministic request-building
pipeline survive the diff shape without crashing or mis-encoding."

**Why:** tonight's dispatch named "golden-diff test corpus" as a good
overnight category; live check (`grep -in "mode.change|pure.delete|multi.hunk|
executable.bit" src/request.rs`) confirmed zero existing coverage for these
three common shapes, and the existing 11-test suite has no consolidated
fixture home for diff-shape regressions.
