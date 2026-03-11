# PR Walkthrough: Issue #298

## Goal

Teach the `trace` reviewer to follow swallowed-error propagation chains so it flags downstream crashes or corruption after a logged-but-ignored failure.

## Before

- `trace` explicitly checked local error handling, but not the caller path after an error was logged and execution continued.
- Swallowed-error bugs like `if err != nil { log.Warn(...) }` followed by `resp.Name` could slip through as PASS or low-signal feedback.
- There was no targeted prompt-contract test or eval fixture protecting this failure mode.

## After

- `.opencode/agents/correctness.md` now includes an `Error Propagation Chains` section.
- The guidance tells `trace` to identify the result value left in scope on the error path, trace downstream uses, and flag unchecked dereferences or method calls as `major`.
- Safe-path exemptions are explicit: safe fallback assignment, nil/zero guards, and immediate returns after logging should not be flagged.
- The new contract is protected by `tests/test_error_propagation_guidance.py` and a swallowed-error correctness fixture in `evals/promptfooconfig.yaml`.

## Verification

- RED:
  - `python3 -m pytest tests/test_error_propagation_guidance.py -q`
  - Outcome before prompt change: `5 failed`
- GREEN:
  - `python3 -m pytest tests/test_error_propagation_guidance.py -q`
  - `python3 -m pytest tests/test_defaults_change_awareness.py tests/adversarial/test_harness.py -q`
  - `python3 -m ruff check .opencode/agents/correctness.md tests/test_error_propagation_guidance.py`
- Repo gate:
  - `make validate`
  - Final outcome on this branch after rebase and review fixes: `1551 passed, 1 skipped`, `ruff` clean, `shellcheck` clean.

## Persistent Check

`make validate`
