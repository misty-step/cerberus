# Issue #312 Walkthrough: AC compliance in verdict JSON and PR comment

## Claim

Cerberus now carries acceptance-criteria compliance through the full verdict
pipeline: structured extraction can emit reviewer-level `ac_compliance`,
`parse-review.py` validates and normalizes it, `aggregate-verdict.py`
deduplicates it conservatively, and the verdict PR comment renders the result as
an AC checklist.

## What Changed

- Extended the shared verdict schema with an optional `ac_compliance` object:
  counts plus per-AC `details[]` containing `ac`, `status`, and `evidence`.
- Tightened `extract-verdict.py` so the structured extraction prompt populates
  `ac_compliance` when reviewer scratchpads evaluate acceptance criteria.
- Updated the correctness reviewer prompt to keep a short `## Spec Compliance`
  checklist in its scratchpad so extraction has a stable source.
- Added parser-side validation and count normalization so malformed or
  hallucinated AC totals do not leak through the contract.
- Added aggregate-side dedupe with conservative status precedence:
  `NOT_SATISFIED` beats `SATISFIED`, which beats `CANNOT_DETERMINE`.
- Added verdict comment rendering for a scannable `### AC Compliance` checklist.

## Design Note

- Issue #312 suggested regex extraction from reviewer free text.
- This lane intentionally does not do that.
- Cerberus is LLM-first for semantic extraction, and the repo already had a
  structured extraction step. The smallest coherent fix was to extend that
  contract instead of adding a second heuristic parser.

## Persistent Verification

```bash
python3 -m pytest \
  tests/test_extract_verdict.py \
  tests/test_parse_review.py \
  tests/test_aggregate_verdict.py \
  tests/test_render_verdict_comment.py \
  tests/test_spec_compliance_guidance.py -q

make validate
```

## Observed Result

- `python3 -m pytest tests/test_extract_verdict.py tests/test_parse_review.py tests/test_aggregate_verdict.py tests/test_render_verdict_comment.py tests/test_spec_compliance_guidance.py -q`
  - `458 passed`
- `make validate`
  - Python test suite passed: `1910 passed, 1 skipped`
  - `ruff` clean
  - `shellcheck` clean
  - `cerberus-elixir` checks passed

## Before / After

- Before: reviewer notes could discuss AC satisfaction, but verdict JSON had no
  structured AC payload and the PR comment did not surface the information as a
  checklist.
- After: AC status can flow from reviewer scratchpad notes into verdict JSON and
  the verdict comment shows an explicit checklist for authors and downstream
  tooling.

## Residual Gap

- This lane hardens the extraction, aggregation, and rendering contract, but it
  still relies on reviewers writing meaningful spec-compliance notes in their
  scratchpads. If recall is weak in live runs, the next follow-up is prompt/eval
  hardening rather than more deterministic parsing glue.
