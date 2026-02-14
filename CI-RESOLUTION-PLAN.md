# CI Resolution Plan

- [x] [CI FIX] Reduce `pre-commit` YAML/JSON validation spawn overhead
  - **Files:** `.githooks/pre-commit`
  - **Issue:** O(n) process spawning by invoking `python3 -c` for each YAML/JSON file.
  - **Cause:** Python startup overhead accumulates with many staged files and breaks the hook’s fast-check goal.
  - **Fix:** Collect validated filenames into arrays and run one Python interpreter per format.
  - **Implementation:**
    - Build `yaml_to_check` and `json_to_check` arrays from staged file lists.
    - Use a single `python3 -` heredoc invocation for each format, iterating filenames in-process.
    - Preserve per-file reporting and keep global `errors` aggregation.
  - **Verification:** Manual review and follow-up CI run expected to clear VULCAN major findings.
  - **Estimate:** 15m

- [ ] [CI FIX] Confirm post-change performance in CI reviewer gate
  - **Files:** `.github/workflows/ci.yml` (indirect through changed hook behavior)
  - **Issue:** Need to ensure VULCAN verdict moves to PASS/WARN without major regressions.
  - **Cause:** Dependent on repository reviewer execution path.
  - **Fix:** Push patch and rerun CI for PR #170 checks.
  - **Verification:** `Cerberus Council` should no longer report VULCAN FAIL for this hook.
  - **Estimate:** 10m

- [ ] [CODE FIX] Optional hardening (follow-up)
  - **Files:** `.githooks/pre-push`
  - **Issue:** Existing minor feedback outside active failure is still open (`ruff_paths` empty-array handling under `set -u`).
  - **Cause:** Potential older Bash compatibility concern.
  - **Fix:** Guard array-length checks with safe expansions in follow-up PR if needed.
  - **Verification:** No behavior change required for current CI fail, run follow-up review pass.
  - **Estimate:** 20m
