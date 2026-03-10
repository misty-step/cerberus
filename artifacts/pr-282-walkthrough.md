# PR Walkthrough: Issue #282

## Goal

Stop `parse-review.py` from misclassifying timeout or ambiguous parse-failure output as `API_KEY_INVALID`.

## Before

- Bare `authentication` text in unstructured output could trip `looks_like_api_error()` and emit `API_KEY_INVALID`.
- `RATE_LIMIT` skips inherited the generic "Check API key and quota settings." guidance.
- Result: timeout and provider-output failures could show up as auth problems in downstream verdict surfaces.

## After

- `looks_like_api_error()` now requires corroborating auth-failure evidence around `authentication`.
- Explicit timeout markers still win and now have a regression test that includes incidental auth wording.
- `generate_skip_verdict()` now emits error-specific operator guidance for `RATE_LIMIT`, `SERVICE_UNAVAILABLE`, and generic `API_ERROR`.

## Verification

- Focused RED -> GREEN:
  - `python3 -m pytest tests/test_parse_review.py -q -k 'timeout_marker_beats_authentication_heuristic or ambiguous_authentication_text_does_not_map_to_key_invalid or rate_limit_error_suggestion_does_not_blame_api_key'`
- Broader parser coverage:
  - `python3 -m pytest tests/test_parse_review.py -q`
- Downstream rendering guard:
  - `python3 -m pytest tests/test_parse_review.py tests/test_render_findings.py tests/test_render_verdict_comment_helpers.py -q`
- Repo gate:
  - `make validate`
  - Outcome: full pytest stage passed (`1526 passed, 1 skipped`), then `ruff` failed on unrelated pre-existing issues outside this change.

## Persistent Check

`python3 -m pytest tests/test_parse_review.py -q`
