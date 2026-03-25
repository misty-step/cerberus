# Migrating to API Mode

Cerberus now uses one supported GitHub Action path: the root action dispatches to the hosted Cerberus API.

## What Changed

| Area | Before | Now |
|------|--------|-----|
| Action entrypoint | reusable workflow or decomposed matrix jobs | root `misty-step/cerberus@master` action |
| Secret | `CERBERUS_OPENROUTER_API_KEY` | `CERBERUS_API_KEY` |
| URL config | implicit local review pipeline | hosted URL default, optional `cerberus-url` override |
| Review execution | GitHub Actions matrix in this repo | hosted Cerberus API + Elixir engine |

## New Workflow

```yaml
name: Cerberus Review

on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]

permissions:
  contents: read
  issues: write
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    if: github.event.pull_request.draft == false
    steps:
      - uses: misty-step/cerberus@master
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          api-key: ${{ secrets.CERBERUS_API_KEY }}
```

## Migration Steps

1. Delete the old reusable-workflow or decomposed matrix jobs.
2. Add the `CERBERUS_API_KEY` secret.
3. Replace the workflow with the root-action version above.
4. If you self-host Cerberus, add `cerberus-url: https://<your-cerberus>.fly.dev`.
5. Open a non-draft PR and verify a verdict is returned.

## Notes

- Fork PRs still skip.
- Draft PRs still skip.
- `fail-on-verdict` defaults to `true`.
- The OpenRouter key now belongs on the Cerberus server, not in the consumer repository.
