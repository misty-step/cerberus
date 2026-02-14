# CI Resolution Plan

## Root cause
- **Classification:** Code issue
- **Cause:** `defaultTest.options.transform` is now compilable, but smoke eval is currently failing at assertion/runtime level in `evals/promptfooconfig.yaml` checks.
- **Impact:** 30 assertion mismatches plus one runtime assertion error still keep the suite at 0% pass despite stable workflow plumbing.

- **Location:** `evals/promptfooconfig.yaml` (assertions and transform normalization points), with current evidence from smoke workflow run `22024931706`.
- **Error introduced by:** current suite tuning after transform repair; assertion robustness and expected-output normalization still need adjustment.

## Planned fixes

- [x] [CODE FIX] Replace inline transform with expression-safe IIFE form
  ```
  Files: evals/promptfooconfig.yaml:567
  Issue: `Unexpected token 'try'` errors from Promptfoo transform parser
  Cause: transform was provided as bare statement syntax instead of expression-compatible form
  Fix: use `(() => { ... })()` wrapper so the transform is a valid expression and retains JSON fallback parsing
  Verify: rerun `smoke-eval` workflow and confirm transform errors disappear
  Estimate: 10m
  ```

- [x] [CI FIX] Revalidate smoke-eval threshold behavior after transformation fix
  ```
  Files: .github/workflows/smoke-eval.yml (observability only)
  Issue: pass rate currently reads as 0% because all tests were transform-failing
  Cause: downstream check is a symptom of earlier parser failure
  Fix: rerun smoke-eval from current branch head and confirm pass-rate computation reflects test assertions
  Verify: `Results: 0 passed` should no longer be constant failure from parse phase
  Estimate: 5m
  ```

- [ ] [CODE FIX] Harden assertion shape handling for SQL/critical first-pass case
  ```
  Files: evals/promptfooconfig.yaml
  Issue: `TypeError: Cannot read properties of undefined (reading 'includes')` on `output.findings` path
  Cause: brittle optional field access inside custom JS assertion
  Fix: switch to optional chaining and existence checks in the affected assertion
  Verify: rerun smoke-eval and confirm the runtime error is eliminated
  Estimate: 15m
  ```

- [ ] [CODE FIX] Improve output normalization in transform/validator
  ```
  Files: evals/promptfooconfig.yaml
  Issue: 30 assertion mismatches after transform syntax repair
  Cause: judge output variants are not always mapped into stable PASS/FAIL schema expected by assertions
  Fix: normalize verdict case, handle common response variants, and keep explicit fallback semantics for non-JSON output
  Verify: rerun smoke-eval and confirm pass rate moves above threshold or identify remaining false-negative tests explicitly
  Estimate: 30m
  ```

## Prevention
- Keep Promptfoo transform expressions in expression-safe form (IIFE) and avoid statement-style snippets unless docs confirm body-mode execution.
- Add a minimal smoke test config entry with a known fixture output when touching eval transform logic.
