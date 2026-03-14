# PR 317 Walkthrough

## Merge Claim

Cerberus now accepts whole-number percentage confidence values like `100` by normalizing them to the unit interval at parse time, while the shared extraction schema explicitly keeps the contract at `0..1`.

## Why This Matters

Before this branch, a reviewer could emit a valid PASS verdict with no findings and still fail the run if it wrote `confidence: 100`. That turned a harmless formatting drift into a false-negative CI failure.

After this branch:
- `scripts/parse-review.py` converts whole-number percentage confidence values in `(1, 100]` to `0..1`
- ambiguous fractional out-of-range values such as `1.5` still fail
- `scripts/lib/review_schema.py` now advertises the correct bounded confidence contract
- regression tests lock both layers

## Evidence Script

1. Show the focused regression gate:
   - `python3 -m pytest tests/test_parse_review.py tests/test_extract_verdict.py -q`
   - Result: `187 passed in 5.09s`
2. Show the full repo quality gate:
   - `make validate`
   - Result: `1731 passed, 1 skipped in 54.25s`
   - Followed by clean `ruff` and `shellcheck`

## Before / After

### Before
- Parser rejected `confidence: 100` as out of range.
- Structured extraction schema accepted any numeric confidence value.
- Downstream repos could fail despite a PASS verdict with zero findings.

### After
- Parser normalizes whole-number percentage confidence values such as `100` to `1.0`.
- Fractional out-of-range values remain invalid.
- Shared schema now declares `minimum: 0` and `maximum: 1`.

## Files To Review

- `scripts/parse-review.py`
- `scripts/lib/review_schema.py`
- `tests/test_parse_review.py`
- `tests/test_extract_verdict.py`

## Persistent Verification

- Primary check: `make validate`
- Focused regression check: `python3 -m pytest tests/test_parse_review.py tests/test_extract_verdict.py -q`

## Residual Gap

This lane normalizes clearly percentage-style whole numbers only. If future reviewer outputs start emitting ambiguous fractional percentages like `1.5`, that would need a separate contract decision rather than silent coercion.
