# CI Failure Summary

## Workflow
- Name: `Eval - Smoke`
- Workflow file: `.github/workflows/smoke-eval.yml`
- Job: `smoke-eval`
- Failing run: `https://github.com/misty-step/cerberus/actions/runs/22020852635`

## Command
```bash
promptfoo eval --config evals/promptfooconfig.yaml --no-cache --max-concurrency 3
```

## Exit code
- `smoke-eval` job exited non-zero (`Process completed with exit code 1`)
- Final pass check command failed at `Pass rate` assertion

## Error message (exact)
```text
Error creating inline transform function: Unexpected token 'try'
Provider call failed during eval
{
  "name": "SyntaxError",
  "message": "Unexpected token 'try'"
}
...
Results: 0 passed, 0 failed, ✗ 31 errors (0%)
Smoke eval failed: 0% < 75% threshold
```

## Location
- Environment:
  - `Ubuntu 24.04.3` runner
  - Node: `v20.20.0`
  - `promptfoo@0.120.24`
- Configuration line: `evals/promptfooconfig.yaml:567`
- Offending expression: `defaultTest.options.transform`

## Stack/trace notes
- Failures occur before assertions execute in each test case.
- 31 transform parse failures were logged (`provider call failed during eval`) and the run never produced successful parsed output JSON.

## Error summary
- CI failure is consistent and deterministic for this run, not intermittent.

---

## Subsequent failure (run 22026446425)

## Failing check
- **Workflow:** `Eval - Smoke`
- **Run:** `22026446425`
- **Job:** `smoke-eval`
- **Step:** `Run smoke eval`
- **Exit code:** `100` (from `promptfoo eval`)

## Error summary (exact)
```log
Provider call failed during eval
Error: Transform function did not return a value
##[error]Process completed with exit code 100.
```

## Notes
- Cerberus is green: `Cerberus Verdict` passed on run `22026446412`.
- This smoke-eval failure happened in the eval step before pass-rate enforcement, so results weren't meaningful (`31 errors`).
