# Issue 355 Walkthrough: Parser Diagnostics Envelope

## Claim

`parse-review.py` no longer leaks parser-only diagnostics through ad hoc review
contract fields. Stats corrections and stale-knowledge annotations now live in a
single `_diagnostics` envelope, while reviewer findings keep the exact schema.

## Evidence

- Targeted regression transcript:
  - `docs/walkthroughs/issue-355-parse-review-verification.txt`
- Full validation transcript:
  - `docs/walkthroughs/issue-355-full-validation.txt`

## What To Look For

- `tests/test_parse_review.py` asserts `_stats_discrepancy` is gone from the
  review root and `_stale_knowledge_annotated` is gone from findings.
- The same tests assert `_diagnostics.stats_discrepancy` and
  `_diagnostics.stale_knowledge_annotations` carry the pipeline-only metadata.
- The focused parser regressions now also prove both parser-owned diagnostics
  can coexist in the same envelope.
- Full repo verification, `ruff`, and `shellcheck` all finish green on the
  rebased branch.

## Persistent Verification

- `pytest tests/test_parse_review.py tests/test_extract_verdict.py tests/test_render_findings.py -q`
- `PYTHONPATH=. pytest tests/ -x -v`
- `ruff check scripts/ matrix/ tests/`
- `find scripts tests -name "*.sh" -type f -exec shellcheck {} +`

## Residual Gap

- Local `make validate` currently drifts from CI and the available shell
  toolchain because the Makefile still assumes `python3 -m pytest ... --timeout=30`.
  Follow-up: issue #366.
