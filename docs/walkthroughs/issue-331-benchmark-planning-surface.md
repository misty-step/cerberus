# Issue #331 Walkthrough: benchmark planning surface alignment

## Claim

Cerberus now keeps the benchmark-driven recall epic honest in both places that matter: the repo-backed planning mirror names every shipped child lane with benchmark evidence and verification, and the GitHub epic checklist matches the actual child-issue state.

## What Changed

- Replaced the stale "Current Reviewer Hardening Tracks" block in `docs/BACKLOG-PRIORITIES.md` with a repo-local planning mirror for epic `#331`.
- Added explicit tracking, status, benchmark evidence, and verification lines for all benchmark-backed child lanes:
  - `#332` benchmark loop
  - `#333` security/dataflow hardening
  - `#334` large-PR timeout reduction
  - `#335` lifecycle/state-machine reasoning
  - `#336` adjacent-regression detection
  - `#375` reviewer presence monitoring
  - `#57` typed repo/GitHub context access
  - `#381` prompt-contract simplification
  - `#380` agentic-review eval coverage
- Tightened `tests/test_reviewer_benchmark_docs.py` so each tracked workstream must keep both benchmark evidence and verification, not just an issue number.
- Refreshed GitHub issue `#331` so the child checklist, source-artifact list, and planning-surface wording match the repo-backed mirror.

## RED / GREEN

### RED

- A contract check run against the pre-change `HEAD:docs/BACKLOG-PRIORITIES.md` failed because the backlog mirror:
  - omitted verification lines for the tracked workstreams
  - omitted the prompt-contract and eval-coverage lanes entirely
  - used outdated section names that no longer matched the epic acceptance criteria

### GREEN

```bash
pytest -q tests/test_reviewer_benchmark_docs.py tests/test_reviewer_benchmark_skill.py tests/test_dogfood_presence.py
pytest -q tests/test_security_prompt_contract.py tests/test_review_slicing.py tests/test_lifecycle_state_reasoning.py tests/test_adjacent_regression_guidance.py tests/test_agentic_review_eval_contract.py tests/test_review_prompt_project_context.py tests/test_repo_read_contract.py tests/test_github_read_contract.py tests/test_github_read_integration.py
make validate
```

- Targeted benchmark-planning suite: `56 passed`
- Referenced child-lane verification suites: `115 passed`
- Full repo gate: `1955 passed, 1 skipped`
- `ruff`, `shellcheck`, `yamllint`, and `cerberus-elixir` checks all completed successfully under `make validate`

## Before / After

- Before: the repo mirror only tracked a subset of the epic, lacked explicit verification targets, and drifted from the actual closed child-issue set in GitHub.
- After: the repo mirror and epic both present the same nine-lane benchmark program, each lane carries evidence plus a durable verification hook, and future drift will fail a dedicated doc-contract test.

## Persistent Verification

```bash
pytest -q tests/test_reviewer_benchmark_docs.py tests/test_reviewer_benchmark_skill.py tests/test_dogfood_presence.py
make validate
```

## Scope Notes

- No browser or frontend walkthrough was needed. This lane changes planning metadata and regression coverage, not runtime user flows.
