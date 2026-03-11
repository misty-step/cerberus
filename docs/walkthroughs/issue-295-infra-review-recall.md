# Issue #295 Walkthrough: Infra Review Recall Hardening

## Summary

This lane hardens reviewer guidance for infrastructure-heavy PRs without changing the verdict schema. The fix teaches:

- `trace` to cross-check deployment/config diffs against unchanged startup file reads and format-sensitive configuration usage.
- `guard` to treat Dockerfile and `.dockerignore` changes as first-class security surfaces, including secret bake-in risk and missing non-root `USER`.
- `parse-review.py` to document the intended boundary for `[unverified]` / `suggestion_verified`: behavioral uncertainty only, not direct static observations.

## Before

- `trace` had strong diff-local correctness guidance, but no explicit instruction to inspect unchanged startup readers when `.dockerignore` or deployment config changed.
- `guard` covered general secret/config risks, but did not explicitly own `.dockerignore` omissions, root-container checks, or the higher blast radius of infra-only PRs.
- The parser already preserved severity for `suggestion_verified: false`, but that contract was implicit rather than codified near the parser boundary.

## After

- `trace` now runs an infrastructure configuration cross-check when deployment/config files change and treats cross-file startup breakage as in scope.
- `guard` now runs an infrastructure threat-model pass for Dockerfile / `.dockerignore` changes and forbids `[unverified]` on directly-readable static evidence.
- `parse-review.py` now documents the static-vs-behavioral boundary so prompt guidance and parser behavior stay aligned.
- Regression tests fail if that guidance disappears.

## Verification

Persistent verification for this path:

```bash
python3 -m pytest tests/test_infra_prompt_guidance.py tests/test_parse_review.py -q
```

Observed result on this branch:

- Targeted command passed on this branch

Broader repo gate:

```bash
make validate
```

Observed result on this branch:

- Full test suite passed: `1539 passed, 1 skipped`
- `ruff` still fails on pre-existing unrelated findings outside this diff

## Why This Is Better

The previous failure mode was not missing deterministic detectors; it was missing reviewer intent. This fix addresses the root cause at the prompt boundary, keeps the parser contract explicit, and adds low-cost regression coverage so these instructions do not silently drift.
