# Issue 355 Walkthrough: Parser Diagnostics Envelope

## Claim

`parse-review.py` no longer leaks parser-only diagnostics through ad hoc review
contract fields. Stats corrections and stale-knowledge annotations now live in a
single `_diagnostics` envelope, while reviewer findings keep the exact schema.

## Evidence

- Targeted regression transcript:
  - `docs/walkthroughs/issue-355-parse-review-verification.txt`
- Full repo gate transcript:
  - `docs/walkthroughs/issue-355-make-validate.txt`

## What To Look For

- `tests/test_parse_review.py` asserts `_stats_discrepancy` is gone from the
  review root and `_stale_knowledge_annotated` is gone from findings.
- The same tests assert `_diagnostics.stats_discrepancy` and
  `_diagnostics.stale_knowledge_annotations` carry the pipeline-only metadata.
- `make validate` finishes green, proving the schema split did not regress the
  wider repo contract.

## Persistent Verification

- `python3 -m pytest tests/test_parse_review.py tests/test_extract_verdict.py tests/test_render_findings.py -q`
- `make validate`
