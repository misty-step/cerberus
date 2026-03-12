# Issue #305 Walkthrough: unverified findings stay visible and count

## Summary

This lane finishes the unverified-findings contract instead of letting the parser quietly drift:

- `parse-review.py` now normalizes explicit unverified markers onto stable metadata.
- Verdict recomputation treats those findings as discounted signal instead of zero signal.
- Findings rendering accepts the normalized metadata so the PR comment still shows the uncertainty clearly.
- Repository docs no longer claim the parser demotes unverified or speculative findings to `info`.

## Before

- The parser already preserved severity for several older downgrade paths, but verdict recomputation did not have a first-class weighted path for explicitly unverified findings.
- Rendering only looked for `_evidence_unverified`, which left the newer `_unverified` shape under-specified.
- `CLAUDE.md` still described the old demotion behavior, which made the contract misleading for future contributors.

## After

- Explicit unverified findings (`_unverified`, `_evidence_unverified`, or `[unverified]` title prefix) are normalized into one parser-side contract.
- Verdict recomputation discounts unverified findings at 50% weight, so `2` unverified majors now force `WARN` and `4` force `FAIL`.
- Unverified criticals stay visible as critical findings but no longer hard-fail the review by themselves; they surface as warn-level signal until confirmed.
- Rendering reads either unverified metadata shape and keeps the uncertainty note visible next to the finding.
- The contributor docs now match the parser’s real behavior.

## Verification

Persistent verification for this path:

```bash
python3 -m pytest tests/test_parse_review.py tests/test_render_findings.py tests/test_infra_prompt_guidance.py -q
make validate
```

Observed on this branch:

- Targeted suite passed: `166 passed`
- Full repo gate passed: `1559 passed, 1 skipped`

## Why This Is Better

The old failure mode was no longer a raw severity demotion bug; it was contract drift. This fix makes the parser, renderer, tests, and docs agree on one rule: uncertainty can discount a finding, but it cannot bury it.
