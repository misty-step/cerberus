# CI Failure Summary (historical)

## Workflow
- **Name:** `Eval - Smoke`
- **Workflow file:** `.github/workflows/smoke-eval.yml`
- **Job:** `smoke-eval`
- **Status:** Assertion-level failures after transform fix.

## Latest observed failure
- **Command:** `promptfoo eval --config evals/promptfooconfig.yaml --no-cache --max-concurrency 3`
- **Error pattern:** `Results: 0 passed, ✗ 30 failed, ✗ 1 error (0%)`
- **Failure detail:** `TypeError: Cannot read properties of undefined (reading 'includes')`
- **Likely cause:** brittle assertion in `output.findings...toLowerCase()` and low-confidence output parsing/normalization behavior from the judge responses.
- **Impact:** 31 tests run on this branch, with no passing assertions and one assertion runtime error, so threshold gates still fail even after transform syntax repair.

## Current status
- `defaultTest.options.transform` uses an IIFE expression wrapper and is no longer throwing parser errors.
- Remaining failures appear to be in assertion expectations / model-output interpretation, not workflow plumbing.
- Latest observed dataset result on this branch: `0 passed, 30 failed, 1 error` at run `22024931706`.
