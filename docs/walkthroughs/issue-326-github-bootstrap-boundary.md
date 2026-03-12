# Issue 326 Walkthrough: GitHub Bootstrap Boundary

## Claim

Cerberus no longer owns raw `gh pr diff` and `gh pr view` bootstrap logic inside `action.yml`. The review action now delegates PR diff/context fetch to `scripts/fetch-pr-bootstrap.py`, and that helper routes transport, retry, timeout, and failure classification through `scripts/lib/github_platform.py`.

## What Changed

- Added adapter-backed bootstrap fetches to `scripts/lib/github_platform.py`:
  - `fetch_pr_diff(...)`
  - `fetch_pr_context(...)`
  - `GitHubAuthError` and `GitHubTimeoutError` for deterministic bootstrap failure classes
- Added `scripts/fetch-pr-bootstrap.py` to write `pr.diff`, `pr-context.json`, and a structured result file for workflow error plumbing.
- Simplified `action.yml` so the fetch step now delegates bootstrap transport work to the helper and keeps only workflow output plumbing plus remediation text.
- Updated bootstrap regression tests to lock the thinner workflow shape and the new adapter path.
- Updated contract/docs so the review-run bootstrap boundary matches the shipped implementation.

## Before

- `action.yml` owned raw `gh pr diff` and `gh pr view` calls directly.
- Auth retry, timeout handling, and error classification for PR metadata fetch lived in workflow shell.
- The GitHub platform boundary covered review-path helpers, but not the review bootstrap path itself.

## After

- `action.yml` delegates bootstrap fetch to `scripts/fetch-pr-bootstrap.py`.
- `scripts/fetch-pr-bootstrap.py` delegates transport behavior to `scripts/lib/github_platform.py`.
- Bootstrap failure kinds are explicit and stable enough for the workflow to map back into `pr-context-error-*` outputs without re-implementing transport logic.

## Evidence

- Targeted bootstrap proof: `docs/walkthroughs/issue-326-github-bootstrap-targeted-tests.txt`
- Full branch gate: `docs/walkthroughs/issue-326-github-bootstrap-make-validate.txt`

## Persistent Verification

- `make validate`

## Scope Notes

- No browser or frontend walkthrough was needed. This lane changes internal GitHub bootstrap behavior only, so the truth artifact is terminal execution plus the focused workflow/adapter regression suite.
