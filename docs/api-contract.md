# Cerberus API Contract

HTTP API for dispatching review runs to the Cerberus Elixir engine.

The primary client in this repository is the root GitHub Action:

- `action.yml`
- `dispatch.sh`

## Base URL

- Hosted: `https://<your-cerberus>.fly.dev`
- Local: `http://localhost:4000`

## Authentication

All endpoints except `/api/health` require a Bearer token:

```text
Authorization: Bearer <CERBERUS_API_KEY>
```

## Endpoints

### `POST /api/reviews`

Starts an asynchronous review run.

```json
{
  "repo": "owner/repo",
  "pr_number": 42,
  "head_sha": "abc123def456",
  "model": "openrouter/moonshotai/kimi-k2.5"
}
```

### `GET /api/reviews/:id`

Returns the current status and, when complete, the aggregated verdict.

### `GET /api/health`

Simple liveness probe:

```json
{"status":"ok"}
```

## Polling Pattern

`dispatch.sh` implements the canonical client loop:

1. Validate fork / draft / missing-input preconditions.
2. `POST /api/reviews`.
3. Poll `GET /api/reviews/:id` every `poll-interval` seconds.
4. Emit `verdict` and `review-id` outputs.
5. Exit non-zero on API failure or configured failing verdict.

## Action Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `api-key` | yes | - | API auth token |
| `cerberus-url` | yes | - | API base URL |
| `github-token` | no | `''` | Reserved for server-side GitHub operations |
| `model` | no | `''` | Optional model override |
| `timeout` | no | `600` | Max wait time in seconds |
| `poll-interval` | no | `5` | Poll interval in seconds |
| `fail-on-verdict` | no | `true` | Fail the workflow on `FAIL` |

## Environment Variables

### Server

| Variable | Required | Description |
|----------|----------|-------------|
| `CERBERUS_API_KEY` | yes | API auth token |
| `CERBERUS_OPENROUTER_API_KEY` | yes | LLM provider key |
| `OPENROUTER_API_KEY` | no | Legacy alias |
| `PORT` | no | HTTP port |
| `CERBERUS_DB_PATH` | no | SQLite path |

### Client

| Input | Required | Description |
|-------|----------|-------------|
| `api-key` | yes | `CERBERUS_API_KEY` value |
| `cerberus-url` | yes | API base URL |
