# Build a diff-shape fixture corpus for request-building robustness

Priority: P3 · Status: ready · Estimate: M

## Goal
`src/request.rs` has 11 unit tests covering individual parsing branches
(rename, missing binary, empty diff) but no single fixture corpus exercises
`build_git_range_request` end-to-end across the diff shapes most likely to
break a review request builder: a file mode change (executable bit flip), a
pure delete (no additions), and a single file with many separated hunks. This
is deterministic request-building coverage only — NOT review-quality/
LLM-faithfulness evals, which stay in Crucible/Daedalus per ADR 0003.

## Oracle
- [ ] A fixture corpus (in `src/request.rs` `#[cfg(test)]` or `tests/`) builds
      a real temp git repo per case and runs `build_git_range_request`
      end-to-end for: (1) executable-bit-only mode change, (2) pure file
      delete, (3) one file with 3+ separated hunks.
- [ ] Each case asserts the resulting `ReviewRequest` is schema-valid
      (`REVIEW_REQUEST_SCHEMA`) and the `ChangedFile`/`Diff` fields are
      populated as expected for that shape (no panic, no silently-empty diff
      body).
- [ ] The corpus carries one doc comment naming its purpose as a home for
      future diff-shape regressions, matching the existing test style already
      in `request.rs` (e.g. `parses_name_status_with_rename_and_type_change`).
- [ ] `./scripts/verify.sh` green.

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
