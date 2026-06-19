# Cerberus

Multi-agent AI code review for GitHub pull requests.

Cerberus now ships as a thin GitHub Action client that dispatches review runs to the hosted Cerberus API. The heavy Python/Shell matrix pipeline has been retired from this repository.

## Resurrection Planning

The repo is being reshaped toward a Rust review engine with source-agnostic
request/artifact contracts. The current Elixir API path remains the legacy
compatibility surface until the Rust backlog proves parity.

- [Rust resurrection shaping](docs/shaping/rust-review-engine-resurrection.md)
- [Legacy surface retirement inventory](docs/shaping/legacy-surface-retirement.md)
- [Backlog priorities](docs/BACKLOG-PRIORITIES.md)
- [Backlog tickets](backlog.d/)

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
          fail-on-verdict: 'true'
```

Required repository configuration:

- Secret: `CERBERUS_API_KEY`

The scaffolder CLI writes the same template:

```bash
npx @misty-step/cerberus init
```

When working from this source checkout, the Rust CLI can create or verify the
workflow and configure the repository secret through `gh`. If
`CERBERUS_API_KEY` is unset and stdin is an interactive Unix TTY, `init`
prompts with hidden input:

```bash
cargo run --locked -p cerberus-cli -- init --repo-root .
```

For noninteractive setup, pipe the key through stdin instead of argv:

```bash
printf '%s' "$CERBERUS_API_KEY" |
  cargo run --locked -p cerberus-cli -- init --repo-root . --api-key-stdin
```

For workflow-file checks that should not touch GitHub secrets, use
`cerberus-cli init-workflow`.

## Action Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `github-token` | no | `''` | GitHub token forwarded to the hosted Cerberus pipeline for per-request PR reads and writes |
| `api-key` | yes | - | Cerberus API authentication key |
| `cerberus-url` | no | `https://cerberus.fly.dev` | API base URL override for self-hosted or non-default deployments |
| `model` | no | `''` | Reserved; accepted but not yet wired to reviewer selection |
| `timeout` | no | `600` | Max seconds to wait for review completion |
| `poll-interval` | no | `5` | Seconds between status polls |
| `fail-on-verdict` | no | `true` | Exit 1 if aggregated verdict is FAIL |

Outputs:

- `verdict`
- `review-id`

## How It Works

1. The root action runs `cerberus-cli github-action-dispatch` from this Rust
   workspace.
2. The Rust dispatcher validates the PR context, skips fork or draft PRs, and
   sends `POST /api/reviews`.
3. The action polls `GET /api/reviews/:id` until the review completes or times out.
4. The aggregated verdict becomes the GitHub Action result.

The legacy compatibility engine lives in
[`cerberus-elixir/`](cerberus-elixir/README.md). The Rust engine target lives in
the workspace crates and is tracked by the backlog.

## Repository Layout

- `action.yml`: thin GitHub Action client that launches the Rust dispatcher
- `crates/`: Rust schemas, core review artifact engine, adapters, and CLI
- `cerberus-elixir/`: legacy Elixir API server and compatibility review engine
- `defaults/`: model and product data consumed by the engine
- `pi/agents/`: reviewer personas
- `templates/`: consumer workflow templates
- `bin/cerberus.js`: compatibility npm scaffolder wrapper
- `cerberus-cli init`: Rust source-checkout scaffolder, hidden prompt, and GitHub secret setup
- `cerberus-cli init-workflow`: Rust workflow-file-only scaffolder path

## Local Verification

```bash
cargo test -p cerberus-cli init_workflow
cargo test -p cerberus-cli --test github_action_entrypoint
cargo test -p cerberus-cli --test github_action_dispatch
node --check bin/cerberus.js
shellcheck cerberus-elixir/deploy-sprite.sh \
  cerberus-elixir/test/release_contract.sh \
  fixtures/harnesses/command-reviewer.sh \
  fixtures/harnesses/live-peer-reviewer.sh
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

Historical docs, walkthroughs, and ADRs may still mention the retired matrix
pipeline. The supported compatibility surface in this repository is now the
API-dispatch action plus the legacy Elixir engine; the Rust-only target and
deletion sequence are tracked in
[`docs/shaping/legacy-surface-retirement.md`](docs/shaping/legacy-surface-retirement.md).
