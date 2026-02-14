# CI Resolution Plan

## Root cause
- **Classification:** Code issue (expected behavior of merge gate)
- **Cause:** `Council Verdict` is FAIL because ARTEMIS + CASSANDRA verdicts are FAIL, so the verdict action exits 1 when `fail-on-verdict: true`.
- **Evidence:** `Cerberus Council` run `22026142556`:
  - `aggregate-verdict: override ... skipped (invalid or SHA mismatch)`
  - `ARTEMIS: FAIL` (maintainability)
  - `CASSANDRA: FAIL` (testing)

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

## Prevention
- Prefer block scalars for embedded JS in YAML (avoid giant quoted one-liners).
- Keep parse-failure fallbacks consistent (scratchpad == SKIP unless we have structured findings).
