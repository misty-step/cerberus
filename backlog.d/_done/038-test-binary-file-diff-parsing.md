# Test binary-file diff parsing end-to-end (numstat + --binary body)

Priority: P2 · Status: done (2026-07-02) · Estimate: S

## Goal
`parse_numstat` (`src/request.rs:453`) parses git's binary-file numstat line
(`-\t-\tpath`, since binary files have no line-count) via
`.parse::<u32>().ok()`, which silently yields `additions: None,
deletions: None` — correct behavior, but nothing exercises it: `request.rs`
has no test with a binary file in the diff, so this path has run unverified
since it was written.

## Oracle
- [x] Unit test `parses_binary_numstat_line_as_no_line_counts` feeds
      `parse_numstat` a raw binary numstat line and asserts
      `additions`/`deletions` are both `None`.
- [x] End-to-end test `build_git_range_request_handles_an_added_binary_file`
      builds a real temp git repo, adds a 1024-byte binary file as a second
      commit, runs `build_git_range_request`, and asserts the file entry has
      `additions: None, deletions: None` and the request's `Diff.body`
      contains git's `GIT binary patch` marker (empirically confirmed via a
      manual `git diff --binary` run before writing the assertion, so it
      matches real git output rather than a guess).
- [x] `./scripts/verify.sh` green.

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
