# Issue 325 Walkthrough: GitHub Platform Adapter Boundary

## Claim

Cerberus review-path GitHub reads and writes now flow through `scripts/lib/github_platform.py`, so comment fetch/write helpers and PR review/file helpers no longer own raw `gh` transport details in multiple modules.

## What Changed

- Added review-path adapter operations to `scripts/lib/github_platform.py` for:
  - issue comment fetch with optional marker short-circuit
  - issue comment create/update
  - PR review listing
  - PR file listing
  - PR review creation
- Reduced `scripts/lib/github.py` to comment marker/idempotency behavior layered on the adapter.
- Reduced `scripts/lib/github_reviews.py` to compatibility wrappers layered on the adapter.
- Simplified `scripts/collect-overrides.py` to reuse the adapter for JSON and comment reads.
- Added focused tests that lock the adapter boundary and wrapper delegation behavior.
- Updated ADR 004 and `CLAUDE.md` so the documented boundary matches the code.

## Before

- `github_platform.py` owned only transport primitives (`run_gh`, `gh_json`, basic issue-comment fetch).
- `github.py` still owned direct comment write calls and pagination behavior.
- `github_reviews.py` still owned PR review/file transport calls and review payload posting.
- The boundary existed, but it was shallow and review-path intent-level operations were still split.

## After

- `github_platform.py` owns the review-path GitHub adapter surface.
- `github.py` and `github_reviews.py` keep stable public behavior while delegating transport details downward.
- Review-path GitHub error handling stays normalized at the adapter boundary instead of being owned by multiple helpers.

## Evidence

- Targeted adapter test transcript: `docs/walkthroughs/issue-325-github-platform-targeted-tests.txt`
- Full validation transcript: `docs/walkthroughs/issue-325-github-platform-make-validate.txt`

## Persistent Verification

- `make validate`

## Scope Notes

- No browser or frontend QA was required. This change is internal-only and the durable proof is the command transcript plus the adapter-focused regression suite.
