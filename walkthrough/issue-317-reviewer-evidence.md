# Issue 317 Reviewer Evidence

- Problem reproduced from downstream evidence: a PASS verdict with `confidence: 100` failed parsing as out of range.
- Root cause: parser and extraction schema disagreed about the allowed confidence contract.
- Fix shape:
  - bound the shared schema to `0..1`
  - normalize whole-number percentage confidence values in the parser
  - preserve failure for ambiguous fractional out-of-range values
- Proof:
  - `python3 -m pytest tests/test_parse_review.py tests/test_extract_verdict.py -q`
  - `make validate`
