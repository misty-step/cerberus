# CI Resolution Plan

## Root cause
- **Classification:** Code issue
- **Cause:** `promptfoo eval` fails with `Transform function did not return a value` after converting the transform to multi-line YAML.
- **Evidence:** `Eval - Smoke` run `22026446425` fails in `Run smoke eval` with exit code `100`.

## Planned fixes

- [x] [CODE FIX] Make Promptfoo transform readable + less error-prone
  ```
  Files: evals/promptfooconfig.yaml:580
  Issue: transform was a 1000+ char one-liner (hard to maintain/debug)
  Fix: convert to YAML block scalar `|` with formatted IIFE + simpler regex escaping
  Verify: `Eval - Smoke` workflow still passes
  ```

- [x] [CODE FIX] Fix inconsistent SKIP handling for unstructured scratchpad output
  ```
  Files: scripts/parse-review.py
  Issue: scratchpad/no-JSON path defaulted to WARN, while fail() treats scratchpad as SKIP
  Fix: make scratchpad/no-JSON fallback SKIP with preserved raw output
  Verify: unit tests + next council run shows fewer false-positive FAILs
  ```

- [x] [CODE FIX] Align eval cases and harden brittle JS assertions
  ```
  Files: evals/promptfooconfig.yaml
  Issue: some test descriptions contradicted diffs; some assertions called .toLowerCase() on non-strings
  Fix: update mis-specified diffs (e.g. "Missing Interface", "Long Function"); wrap finding fields with String(...)
  Verify: `Eval - Smoke` pass rate remains >= threshold
  ```

- [x] [CI FIX] Align smoke/full workflows with stated thresholds and safer jq defaults
  ```
  Files: .github/workflows/smoke-eval.yml, .github/workflows/full-eval.yml
  Issue: smoke threshold in code was 75% but PR acceptance says 80%; full-eval jq arithmetic was brittle
  Fix: set smoke threshold to 80%; use `// 0` jq defaults in full-eval (and baseline compare)
  Verify: smoke-eval still passes; full-eval arithmetic can’t error on missing fields
  ```

- [x] [CODE FIX] Ensure multi-line Promptfoo transform returns a value
  ```
  Files: evals/promptfooconfig.yaml
  Issue: Promptfoo reports "Transform function did not return a value" (31 errors)
  Cause: Promptfoo treats multi-line transform as a function body; the IIFE expression result is not returned
  Fix: prepend `return` so the transform function returns the IIFE value
  Verify: rerun `Eval - Smoke` and confirm errors drop to 0
  ```

- [x] [CI FIX] Don’t fail early on Promptfoo’s non-zero exit codes
  ```
  Files: .github/workflows/smoke-eval.yml, .github/workflows/full-eval.yml
  Issue: promptfoo exits non-zero (e.g. 100) when there are failures/errors, which stops the job before pass-rate logic runs
  Fix: keep `pipefail` but append `|| true` so pass-rate step is the single gate
  Verify: promptfoo runs, results json exists, pass-rate step enforces thresholds
  ```

## Prevention
- Prefer block scalars for embedded JS in YAML (avoid giant quoted one-liners).
- Keep parse-failure fallbacks consistent (scratchpad == SKIP unless we have structured findings).
