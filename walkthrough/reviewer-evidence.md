# Runtime Error Taxonomy Walkthrough

## Claim

`run-reviewer.py` and `parse-review.py` now consume one shared runtime/API error taxonomy, so explicit API markers, redaction, and skip reasons no longer drift across the runner/parser boundary.

## Before

- `scripts/run-reviewer.py` owned its own API error classifier, token redactor, and marker formatter.
- `scripts/parse-review.py` separately classified explicit `API Error:` markers.
- The same failure could be described differently depending on whether it was interpreted during runtime or parsing.

## After

- `scripts/lib/runtime_errors.py` owns explicit API error classification, redaction, and marker rendering.
- `scripts/run-reviewer.py` delegates API error marker creation to the shared module.
- `scripts/parse-review.py` delegates explicit `API Error:` marker parsing to the same classifier.
- Explicit 429-based markers now preserve `RATE_LIMIT` instead of collapsing to generic `API_ERROR`.

## Evidence

- Shared module: [scripts/lib/runtime_errors.py](/Users/phaedrus/.codex/worktrees/d150/cerberus/scripts/lib/runtime_errors.py)
- Runner callsite: [scripts/run-reviewer.py](/Users/phaedrus/.codex/worktrees/d150/cerberus/scripts/run-reviewer.py)
- Parser callsite: [scripts/parse-review.py](/Users/phaedrus/.codex/worktrees/d150/cerberus/scripts/parse-review.py)
- Focused helper coverage: [tests/test_run_reviewer_helpers.py](/Users/phaedrus/.codex/worktrees/d150/cerberus/tests/test_run_reviewer_helpers.py)
- Parser coverage for explicit rate-limit markers: [tests/test_parse_review.py](/Users/phaedrus/.codex/worktrees/d150/cerberus/tests/test_parse_review.py)

## Persistent Verification

`pytest tests/test_run_reviewer_helpers.py tests/test_runtime_facade.py tests/test_parse_review.py tests/test_run_reviewer_runtime.py -q`

Result in this workspace: `209 passed in 18.34s`
