# QA

## Local Checks

```bash
node --check bin/cerberus.js
shellcheck dispatch.sh

cd cerberus-elixir
mix test
mix format --check-formatted
```

## Consumer Smoke Check

1. Install `templates/consumer-workflow-reusable.yml` into a test repository.
2. Set `CERBERUS_API_KEY`.
3. If you are not using the hosted default, set `cerberus-url` in the workflow.
4. Open a non-draft PR from the same repository.
5. Confirm the workflow runs the root action and receives a verdict.

## Expected Behavior

- Fork PRs skip with `SKIP`.
- Draft PRs skip with `SKIP`.
- Missing `CERBERUS_API_KEY` fails fast.
- `FAIL` verdicts fail the workflow when `fail-on-verdict` is `true`.
