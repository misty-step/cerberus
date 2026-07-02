# Test binary-file diff parsing end-to-end (numstat + --binary body)

Priority: P2 · Status: ready · Estimate: S

## Goal
`parse_numstat` (`src/request.rs:453`) parses git's binary-file numstat line
(`-\t-\tpath`, since binary files have no line-count) via
`.parse::<u32>().ok()`, which silently yields `additions: None,
deletions: None` — correct behavior, but nothing exercises it: `request.rs`
has no test with a binary file in the diff, so this path has run unverified
since it was written.

## Oracle
- [ ] A unit test feeds `parse_numstat` a raw numstat line for a binary file
      (`-\t-\timage.png`) and asserts `additions`/`deletions` are both `None`,
      not a parse panic or a spurious `0`.
- [ ] An end-to-end test (real git repo fixture, one binary file added or
      modified) runs `build_git_range_request` and asserts the resulting
      `ReviewRequest` contains the file with `additions: None,
      deletions: None` and a valid (non-empty, UTF-8) `Diff.body` — confirming
      `--binary`'s base85-encoded patch output survives the full pipeline
      without corrupting the request JSON.
- [ ] `./scripts/verify.sh` green.

## Notes
Verified live 2026-07-01: `grep -n "binary" src/request.rs` shows `--binary`
is passed to `git diff` (line 59) but no test constructs a binary-file
scenario; `parse_numstat`'s only existing test
(`parses_numstat_rename_paths_to_new_path`) covers renames, not binary's
`-`/`-` fields.

**Why:** tonight's dispatch named "robustness on weird diffs (binary files,
renames, huge diffs, empty PRs)" as a good overnight category; binary is the
one diff shape with zero test coverage today — renames and empty-diff already
have tests (verified via `grep -n "test" src/request.rs` for
`rename`/`empty`).
