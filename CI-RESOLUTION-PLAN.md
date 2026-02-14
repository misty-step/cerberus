# CI Resolution Plan

## Root cause
- **Classification:** Code issue
- **Cause:** `defaultTest.options.transform` in Promptfoo config used raw `try/catch` statement text instead of a valid expression form expected by Promptfoo for inline transforms.
- **Impact:** All tests failed during inline transform compilation, producing 31 errors and 0% pass rate.

- **Location:** `evals/promptfooconfig.yaml:567`
- **Error introduced by:** commit `f43b66c`

## Planned fixes

- [ ] [CODE FIX] Replace inline transform with expression-safe IIFE form
  ```
  Files: evals/promptfooconfig.yaml:567
  Issue: `Unexpected token 'try'` errors from Promptfoo transform parser
  Cause: transform was provided as bare statement syntax instead of expression-compatible form
  Fix: use `(() => { ... })()` wrapper so the transform is a valid expression and retains JSON fallback parsing
  Verify: rerun `smoke-eval` workflow and confirm transform errors disappear
  Estimate: 10m
  ```

- [ ] [CI FIX] Revalidate smoke-eval threshold behavior after transformation fix
  ```
  Files: .github/workflows/smoke-eval.yml (observability only)
  Issue: pass rate currently reads as 0% because all tests were transform-failing
  Cause: downstream check is a symptom of earlier parser failure
  Fix: rerun smoke-eval from current branch head and confirm pass-rate computation reflects test assertions
  Verify: `Results: 0 passed` should no longer be constant failure from parse phase
  Estimate: 5m
  ```

## Prevention
- Keep Promptfoo transform expressions in expression-safe form (IIFE) and avoid statement-style snippets unless docs confirm body-mode execution.
- Add a minimal smoke test config entry with a known fixture output when touching eval transform logic.

