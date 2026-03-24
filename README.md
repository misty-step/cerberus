# Cerberus

Multi-agent AI code review for GitHub pull requests.

Cerberus now ships as a thin GitHub Action client that dispatches review runs to the hosted Cerberus API. The heavy Python/Shell matrix pipeline has been retired from this repository.

## Quick Start

Create `.github/workflows/cerberus.yml`:

```yaml
name: Cerberus Review

on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]

permissions:
  contents: read
  issues: write
  pull-requests: write

concurrency:
  group: cerberus-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  review:
    runs-on: ubuntu-latest
    if: github.event.pull_request.draft == false
    steps:
      - uses: misty-step/cerberus@master
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          api-key: ${{ secrets.CERBERUS_API_KEY }}
          cerberus-url: ${{ vars.CERBERUS_URL }}
          fail-on-verdict: 'true'
```

Required repository configuration:

- Secret: `CERBERUS_API_KEY`
- Variable or secret: `CERBERUS_URL`

The scaffolder CLI writes the same template:

```bash
npx @misty-step/cerberus init
```

## Action Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `api-key` | yes | - | Cerberus API authentication token |
| `cerberus-url` | yes | - | Cerberus API base URL |
| `github-token` | no | `''` | Reserved for server-side GitHub operations |
| `model` | no | `''` | Optional model override |
| `timeout` | no | `600` | Max seconds to wait for completion |
| `poll-interval` | no | `5` | Poll interval in seconds |
| `fail-on-verdict` | no | `true` | Exit 1 when the aggregated verdict is `FAIL` |

Outputs:

- `verdict`
- `review-id`

## How It Works

1. The root action runs `dispatch.sh`.
2. `dispatch.sh` validates the PR context, skips fork or draft PRs, and sends `POST /api/reviews`.
3. The action polls `GET /api/reviews/:id` until the review completes or times out.
4. The aggregated verdict becomes the GitHub Action result.

The review engine itself lives in [`cerberus-elixir/`](cerberus-elixir/README.md).

## Repository Layout

- `action.yml` / `dispatch.sh`: thin GitHub Action client
- `cerberus-elixir/`: Elixir API server and review engine
- `defaults/`: model and product data consumed by the engine
- `pi/agents/`: reviewer personas
- `templates/`: consumer workflow templates
- `bin/cerberus.js`: workflow scaffolder CLI

## Local Verification

```bash
node --check bin/cerberus.js
shellcheck dispatch.sh
cd cerberus-elixir && mix test
cd cerberus-elixir && mix format --check-formatted
```

## Docs

- [API contract](docs/api-contract.md)
- [Migration guide](docs/MIGRATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Terminology](docs/TERMINOLOGY.md)
- [Docs index](docs/README.md)

## Legacy Note

Historical docs, walkthroughs, and ADRs may still mention the retired matrix pipeline. The supported product surface in this repository is now the API-dispatch action plus the Elixir engine.
