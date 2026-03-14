# Issue #380 Walkthrough: agentic-review eval contract

## Claim

Cerberus now has an issue-scoped regression layer for agentic review behavior: the shared review prompt treats GitHub comments as untrusted input, Promptfoo config includes four agentic-review fixtures, and repo tests fail if those contract surfaces drift.

## What Changed

- Added `tests/test_agentic_review_eval_contract.py` to lock the new contract:
  - bounded `repo_read` / `github_read` retrieval guidance
  - comment-based prompt injection stays untrusted
  - Promptfoo config contains fixtures for tool selection, linked-context grounding, adjacent-context reads, and prompt-injection resistance
  - eval docs name the contract buckets future fixtures should harden
- Extended `evals/promptfooconfig.yaml` with four agentic-review fixtures tied to the issue intent.
- Updated `templates/review-prompt.md` so GitHub issue/PR comments are explicitly inside the untrusted-input boundary.
- Updated `evals/README.md` so maintainers have one place to extend the agentic-review contract.

## Persistent Verification

```bash
python3 -m pytest tests/test_agentic_review_eval_contract.py tests/test_github_platform.py -q
make validate
```

## Observed Result

- `python3 -m pytest tests/test_agentic_review_eval_contract.py tests/test_github_platform.py -q`
  - `40 passed`
- `make validate`
  - `1749 passed, 1 skipped`
  - `ruff check` clean
  - `shellcheck` clean

## Before / After

- Before: Cerberus had prompt and benchmark fixtures for several recall lanes, but no dedicated regression file or documented contract for agentic-review behavior as a distinct surface.
- After: the repo has an explicit contract and tests for agentic-review retrieval behavior, prompt-injection resistance, and benchmark-inspired adjacent-context coverage.

## Residual Gap

- The strongest remaining gap is live runtime trace proof for the adjacent-context evidence-path AC. This lane verifies the contract surfaces and fixture presence, but it does not add a production-trace replay harness.
