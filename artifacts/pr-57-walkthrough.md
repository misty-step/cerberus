# PR Walkthrough: Issue #57

## Goal

Give reviewer runtimes a typed, read-only local repo context broker so they can fetch changed-file metadata, bounded file slices, diff slices, and repo search results without falling back to generic prompt stuffing.

## Before

- Reviewers had a typed `github_read` tool for live GitHub context.
- Local repo context still depended on generic file tools plus the pre-rendered diff prompt.
- The runtime contract did not expose a single typed, bounded repo broker for changed files, file reads, diff reads, and repo search.

## After

- `pi/extensions/repo-read.ts` adds a typed `repo_read` tool with four bounded actions:
  - `list_changed_files`
  - `read_file`
  - `read_diff`
  - `search_repo`
- The broker now rejects out-of-bounds `read_file` slices, blocks symlink escapes under `workspace_root`, and correctly preserves diff paths containing the token ` b/`.
- `defaults/reviewer-profiles.yml` now loads `repo_read` alongside `github_read` in the shared reviewer runtime contract.
- `templates/review-prompt.md` now tells reviewers to use `repo_read` for local context and `github_read` for GitHub discussion context.
- Contract tests lock the extension surface and the profile/prompt wiring.

## Verification

- RED:
  - `python3 -m pytest tests/test_reviewer_profiles.py tests/test_review_prompt_project_context.py tests/test_repo_read_contract.py tests/test_github_read_contract.py -q`
  - Outcome before tightening the new repo-read contract test: `1 failed, 50 passed`
  - `make validate`
  - Outcome before the final lint fix: `F541 f-string without any placeholders` in `tests/test_repo_read_contract.py`
- GREEN:
  - `npx -y tsx --test tests/extensions/github-read.test.ts tests/extensions/repo-read.test.ts`
  - Outcome: `14 tests, 14 passed`
  - `python3 -m pytest tests/test_reviewer_profiles.py tests/test_github_platform.py tests/test_review_prompt_project_context.py -q`
  - Outcome: `66 passed`
  - `python3 -m pytest tests/test_repo_read_contract.py tests/test_reviewer_profiles.py tests/test_review_prompt_project_context.py -q`
  - Outcome: `40 passed`
  - `make validate`
  - Outcome: `1738 passed, 1 skipped`, `ruff` clean, `shellcheck` clean

## Persistent Check

`make validate`

## Residual Risk

- The new broker is intentionally text-oriented and bounded. It does not add symbol-aware or AST-aware navigation yet.
- Repo search currently uses straightforward recursive text scanning inside the checked-out workspace. That is acceptable for this lane because the contract is typed and bounded, but larger optimization work would belong in a follow-up issue rather than this foundation change.
