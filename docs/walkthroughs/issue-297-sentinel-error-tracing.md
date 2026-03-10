# Walkthrough: Issue #297 Sentinel Error Tracing

## Title

Teach `trace` to catch sentinel-on-error control-flow bugs before they silently terminate loops or misadvance state machines.

## Why now

Reviewer benchmark work showed Cerberus missing phase-spanning correctness bugs where a real failure is rewritten into a sentinel like `ErrNoIssues` or `StopIteration`. Those bugs look harmless at the return site but break caller control flow later, which is exactly the class of issue `trace` should catch.

## Before

- The correctness prompt covered local error handling and state transitions, but it did not force explicit reasoning over sentinel return sites and downstream callers.
- No prompt-contract test ensured `trace` named the loop/state-machine consequence or protected legitimate empty-result sentinel paths from false positives.

## What changed

- Added a `Sentinel Error Tracing` section to [.opencode/agents/correctness.md](/Users/phaedrus/.codex/worktrees/62ae/cerberus/.opencode/agents/correctness.md) that requires:
  - enumerating sentinel return sites
  - separating legitimate empty/done paths from real failure paths
  - tracing caller behavior like loop termination, skipped retries, and bad state-machine advancement
  - recognizing the pattern across Go, Python, JavaScript, and Rust
- Added [tests/test_sentinel_error_tracing.py](/Users/phaedrus/.codex/worktrees/62ae/cerberus/tests/test_sentinel_error_tracing.py) to lock the prompt contract.
- Cleaned [tests/test_defaults_change_awareness.py](/Users/phaedrus/.codex/worktrees/62ae/cerberus/tests/test_defaults_change_awareness.py) so touched-area lint is clean.

## After

- `trace` now has explicit instructions to follow sentinel values across call frames instead of treating the return site as the whole bug.
- The reviewer is told to report both the incorrect sentinel mapping and the downstream caller consequence when a loop or state machine trusts that sentinel.
- Legitimate empty/done sentinel use remains explicitly out of scope.

## Verification

RED:

```bash
python3 -m pytest tests/test_sentinel_error_tracing.py -q
```

Observed before the prompt change: `4 failed`.

GREEN:

```bash
python3 -m pytest tests/test_sentinel_error_tracing.py tests/test_defaults_change_awareness.py tests/adversarial/test_harness.py -q
python3 -m ruff check tests/test_sentinel_error_tracing.py tests/test_defaults_change_awareness.py
```

Observed after the prompt change:

- `22 passed`
- `All checks passed!`

Broader repo gate:

```bash
make validate
```

Observed on 2026-03-10:

- Pytest phase passed: `1540 passed, 1 skipped`
- Lint phase still fails on unrelated pre-existing `ruff` findings in untouched files

## Persistent Verification

`python3 -m pytest tests/test_sentinel_error_tracing.py tests/test_defaults_change_awareness.py tests/adversarial/test_harness.py -q`

This is the durable regression check for the new prompt contract.

## Residual risk

This change hardens the prompt contract, not model behavior itself. A future eval pack with concrete sentinel-on-error replay cases would provide stronger runtime evidence than text-level contract tests alone.
