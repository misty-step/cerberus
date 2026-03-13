# Reviewer Evidence: #333

- Primary artifact: [artifacts/pr-333-walkthrough.md](../artifacts/pr-333-walkthrough.md)
- Core proof: the branch turns three benchmarked security/dataflow misses into explicit prompt contract plus eval coverage, then proves the contract with repo tests
- Protecting checks:
  - `python3 -m pytest tests/test_security_prompt_contract.py tests/test_evals_config.py -q`
  - `make test`

## Fast Review Path

1. Read the new indirect re-entry section in `.opencode/agents/security.md`.
2. Confirm the repo-level checklist alignment in `pi/skills/security-review/SKILL.md`.
3. Inspect the three new replay fixtures in `evals/promptfooconfig.yaml`.
4. Verify the locking tests in `tests/test_security_prompt_contract.py` and `tests/test_evals_config.py`.

## Execution Evidence

- RED: targeted contract suite failed with `7 failed` before the implementation.
- GREEN: the same targeted suite passed with `7 passed in 0.14s`.
- Regression gate: `make lint` passed.
- Full suite: `1692 passed, 1 skipped in 50.12s`.
