# Cerberus Elixir

OTP application powering the Cerberus review engine. Receives review requests via
HTTP API, orchestrates parallel reviewer GenServers, aggregates verdicts, and posts
results to GitHub.

## Architecture

```text
Cerberus.Supervisor (one_for_one)
  ├── Cerberus.Config            — hot-reload persona/model config from defaults/config.yml
  ├── Cerberus.Store             — SQLite persistence (review runs, costs, events)
  ├── Cerberus.ReviewSupervisor  — DynamicSupervisor for reviewer GenServer pools
  ├── Cerberus.TaskSupervisor    — async pipeline execution
  ├── Cerberus.Router            — panel selection based on diff classification
  ├── Cerberus.Telemetry         — OpenTelemetry instrumentation + Langfuse export
  └── Bandit                     — HTTP server (port 4000)
```

## API

Three endpoints, authenticated via Bearer token (`CERBERUS_API_KEY`):

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/reviews` | yes | Start async review run (202) |
| `GET` | `/api/reviews/:id` | yes | Poll status + results (200/404) |
| `GET` | `/api/health` | no | Liveness probe (200) |

See [`docs/api-contract.md`](../docs/api-contract.md) for the full HTTP reference.

## Pipeline

`POST /api/reviews` creates a `queued` review run, then starts the pipeline async:

1. Update status to `running`
2. Fetch PR context + diff from GitHub
3. Start check run (best-effort)
4. Route diff → select reviewer panel (2-4 from 6-reviewer bench)
5. Spawn reviewers in parallel via DynamicSupervisor
6. Each reviewer: load persona prompt → multi-turn LLM conversation with `github_read` tool → parse verdict JSON
7. Persist costs, resolve override, aggregate verdicts with finding dedup
8. Post verdict comment + PR review with inline comments + check run conclusion
9. Update status to `completed` with aggregated verdict

## Reviewer Tools

Reviewers have read-only GitHub access via the `github_read` tool:

- `get_file_contents(path, start_line?, end_line?)` — read file text
- `search_code(query, path_filter?)` — search repository code
- `list_directory(path)` — list directory contents

Shell/bash access is denied.

## Setup

```bash
cd cerberus-elixir
mix deps.get
mix compile
mix test
```

## Running

```bash
# Required
export CERBERUS_API_KEY=your-api-key
export CERBERUS_OPENROUTER_API_KEY=your-openrouter-key

# Optional
export PORT=4000
export CERBERUS_DB_PATH=tmp/cerberus.db
export LANGFUSE_PUBLIC_KEY=...
export LANGFUSE_SECRET_KEY=...

mix run --no-halt
# or: iex -S mix
```

## Deployment

Deployed to a Fly Sprite via `deploy-sprite.sh`. CI/CD auto-deploys on merge to
master when `cerberus-elixir/`, `defaults/`, `pi/`, or `templates/` change.

See `fly.toml` for the declarative deployment config (port, health check, region).

### Required Environment Variables

| Variable | Description | Where Set |
|----------|-------------|-----------|
| `CERBERUS_API_KEY` | Bearer token for API authentication | Sprite env file |
| `CERBERUS_OPENROUTER_API_KEY` | OpenRouter API key for LLM calls | Sprite env file |
| `PORT` | HTTP listen port (default 4000, prod 8080) | `fly.toml` / env |
| `CERBERUS_DB_PATH` | SQLite database path | `fly.toml` / env |
| `CERBERUS_REPO_ROOT` | Path to cerberus repo assets on sprite | `fly.toml` / env |
| `SPRITE_TOKEN` | Fly Sprite auth token (CI/CD only) | GitHub secret |

### Optional Environment Variables

| Variable | Description |
|----------|-------------|
| `LANGFUSE_PUBLIC_KEY` | Langfuse observability public key |
| `LANGFUSE_SECRET_KEY` | Langfuse observability secret key |
| `LANGFUSE_HOST` | Langfuse endpoint (default: cloud.langfuse.com) |

### Manual Deploy

```bash
./deploy-sprite.sh              # deploy (create sprite if needed)
./deploy-sprite.sh bootstrap    # force full bootstrap
./deploy-sprite.sh secrets      # set secrets interactively
./deploy-sprite.sh start        # start the app
```

### CI/CD Deploy

Automated via `.github/workflows/deploy.yml`:
1. Install sprite CLI
2. Authenticate with `SPRITE_TOKEN`
3. Run `deploy-sprite.sh deploy`
4. Verify `/api/health` returns 200
5. Checkpoint on success (rollback anchor)

Failed deploys do not checkpoint — restore the prior checkpoint to roll back.

## Testing

```bash
mix test
mix test --cover
```

All DI seams (Store, GitHub, LLM, Router, Config) are injectable via `opts` keyword lists — tests inject mocked implementations without process-level mocking.
