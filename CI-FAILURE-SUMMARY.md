# CI Failure Summary

## Failing check
- **Workflow:** `Eval - Smoke`
- **Run:** `22026446425`
- **Job:** `smoke-eval`
- **Step:** `Run smoke eval`
- **Exit code:** `100` (from `promptfoo eval`)

## Error summary (exact)
```
Provider call failed during eval
Error: Transform function did not return a value
##[error]Process completed with exit code 100.
```

## Notes
- Council is green: `Council Verdict` passed on run `22026446412`.
- This smoke-eval failure happened in the eval step before pass-rate enforcement, so results weren’t meaningful (`31 errors`).
