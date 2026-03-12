# Issue #305 Walkthrough: findings are first-class, evidence supports them

## Summary

This lane replaces the muddled `unverified finding` language with a cleaner contract:

- reviewer prompts now require exact quoted evidence or omission of the finding
- `parse-review.py` strips legacy unverified markers instead of treating them as a live concept
- findings rendering ignores legacy unverified metadata
- repository docs now define findings, evidence, citations, and verdicts explicitly

## Before

- several prompts still told reviewers to emit weaker `[unverified]` findings when they could not quote exact code
- the parser and renderer still carried legacy `unverified` metadata paths
- the repo had no single terminology reference for core review objects

## After

- all six reviewer prompts now say: quote exact code or omit the finding
- the parser removes legacy `[unverified]` markers and related metadata from reviewer output
- the renderer ignores legacy unverified metadata instead of displaying it as a first-class state
- the repo now has a dedicated terminology document that defines findings, evidence, citations, verdicts, skips, and triage

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

The old failure mode was not only severity demotion; it was vocabulary drift. This fix makes prompts, parser, renderer, tests, and docs agree on one rule: a finding is a first-class reviewer claim, and evidence supports it without creating a second finding category.
