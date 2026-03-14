# Reviewer Delta Triage: PR #383

## Verdict

- Greptile's `3/5` is not just scrupulous caution. It found one real correctness bug in `buildFileSlice`, and other external reviewers found additional real or likely-real edge-case defects that Cerberus did not flag.
- Cerberus was both impaired and blind on this PR:
  - impaired because the Testing reviewer timed out and never completed
  - blind because the remaining Correctness, Security, and Architecture lanes still passed despite real defects in the changed code
- The current Cerberus `PASS` is overconfident.

## Evidence

### Cerberus

- Verdict comment: `6/7 reviewers passed. 1 skipped (Testing).`
- The skipped reviewer was `Testing (proof)` with `Timeout (600s)`.

### Real external findings

- `pi/extensions/repo-read.ts`
  - `buildFileSlice` can return `startLine > endLine` with empty content when `startLine` exceeds the file length. This is a real invariant break that Greptile correctly called out.
  - `resolveWorkspacePath` is only lexical. A symlink inside `workspace_root` can target outside the workspace, allowing `read_file` or `search_repo` to escape the intended boundary. Codex correctly called this out.

### Likely-valid external findings

- `pi/extensions/repo-read.ts`
  - The diff-header regex `^diff --git a\/(.+?) b\/(.+)$` mis-splits valid paths containing the token ` b/`. Gemini and Codex both flagged this. A quick reproduction shows the current parser corrupts `oldPath/newPath` for such headers.

### Useful but non-blocking notes

- `pi/extensions/repo-read.ts`
  - `search_repo.truncated` is conservative and can report `true` when results exactly equal the limit.
- `tests/extensions/repo-read.test.ts`
  - The suite lacks a `pathPrefix` coverage case for `search_repo`.

### Low-signal noise

- `tests/extensions/repo-read.test.ts`
  - CodeRabbit's temp-directory cleanup note is optional hygiene, not a review-recall miss.

## Hardening Work

- Add an eval or contract case for out-of-bounds file-slice requests where `startLine > totalLines`.
- Add a security-focused eval for symlink escapes under `workspace_root`.
- Add a parser edge-case eval for diff headers containing ` b/` inside filenames.
- Treat reviewer timeouts as confidence degradation in the final verdict. A `PASS` with a skipped Wave 1 reviewer should be softer than a full clean pass.
