# Walkthrough: Issue #290

## Summary

This change keeps the verdict job authoritative while making verdict-comment delivery resilient to transient GitHub network failures.

## Before

- `scripts/lib/github.py` only treated HTTP 502/503/504 responses as transient.
- TCP-level failures such as `i/o timeout` were treated as hard command failures.
- The verdict action always inherited the comment-posting exit code, so a `PASS` verdict could still fail the job after a transient comment outage.

## After

- `scripts/lib/github.py` now classifies common TCP connection failures as transient and retries them through the existing retry loop.
- The shared comment helper accepts `--transient-error-exit-code` so callers can choose whether a transient outage should fail the step.
- `verdict/action.yml` now sets transient comment failures to:
  - exit `0` for `PASS` and `WARN`
  - exit `1` for `FAIL`

## Why This Shape Is Better

- Retry classification stays in one place instead of duplicating network heuristics in workflow YAML.
- The verdict action owns the policy decision about whether comment delivery is merge-blocking.
- `FAIL` verdicts remain hard failures, while transient comment outages no longer turn `PASS` into a red check.

## Persistent Verification

- `tests/test_github.py`
- `tests/test_verdict_action.py`

## Commands

```bash
python3 -m pytest tests/test_github.py tests/test_verdict_action.py -q
python3 -m ruff check scripts/lib/github.py tests/test_github.py tests/test_verdict_action.py
```
