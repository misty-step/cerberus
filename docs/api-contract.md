# Cerberus API Contract

HTTP API for dispatching review runs to the Cerberus Elixir engine.
The thin GHA action (`api/action.yml`) is the primary client.

## Base URL

Hosted deployments: `https://<your-cerberus>.fly.dev`
Local development: `http://localhost:4000`

## Authentication

All endpoints except `/api/health` require a Bearer token.

```text
Authorization: Bearer <CERBERUS_API_KEY>
```

Set the `CERBERUS_API_KEY` environment variable on the server.
Invalid or missing tokens return `401`.

## Endpoints

### `POST /api/reviews`

Start an asynchronous review run. Returns immediately with the run ID;
the pipeline executes in the background.

**Request**

```json
{
  "repo": "owner/repo",
  "pr_number": 42,
  "head_sha": "abc123def456",
  "github_token": "ghs_...",
  "model": "openrouter/moonshotai/kimi-k2.5"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `repo` | string | yes | GitHub repository (`owner/repo`) |
| `pr_number` | integer | yes | Pull request number |
| `head_sha` | string | yes | HEAD commit SHA |
| `github_token` | string | no | Request-scoped GitHub token for PR reads and writes. When omitted, the server falls back to `GH_TOKEN` / `GITHUB_TOKEN`. |
| `model` | string | no | Reserved for model override. Accepted but not yet wired to reviewer selection; reviewers use configured pool/policy. |

**Response: `202 Accepted`**

```json
{
  "review_id": 1,
  "status": "queued"
}
```

**Errors**

| Status | Body | Cause |
|--------|------|-------|
| `401` | `{"error": "missing_or_invalid_auth"}` | Missing or invalid Bearer token |
| `422` | `{"error": "missing required field: repo"}` | Validation failure (see message) |
| `500` | `{"error": "store_error"}` | Database write failed |
| `500` | `{"error": "store_unavailable"}` | Store GenServer unreachable |

---

### `GET /api/reviews/:id`

Poll a review run's status and results.

**Response: `200 OK`**

```json
{
  "review_id": 1,
  "repo": "owner/repo",
  "pr_number": 42,
  "head_sha": "abc123def456",
  "status": "completed",
  "aggregated_verdict": {
    "verdict": "PASS",
    "summary": "All 4 reviewers passed.",
    "stats": {
      "total": 4,
      "pass": 4,
      "warn": 0,
      "fail": 0,
      "skip": 0
    },
    "findings_count": 0,
    "cost": {
      "total_usd": 0.0312
    },
    "override": null
  },
  "completed_at": "2026-03-18T14:30:00Z",
  "inserted_at": "2026-03-18T14:28:00Z"
}
```

The `aggregated_verdict` field is `null` while status is `queued` or `running`.

**Errors**

| Status | Body | Cause |
|--------|------|-------|
| `401` | `{"error": "missing_or_invalid_auth"}` | Missing or invalid Bearer token |
| `404` | `{"error": "not_found"}` | No review run with that ID |

---

### `GET /api/health`

Liveness probe. No authentication required.

**Response: `200 OK`**

```json
{
  "status": "ok"
}
```

## Status Lifecycle

```text
queued ──> running ──> completed
                  └──> failed
```

| Status | Meaning |
|--------|---------|
| `queued` | Review run created; pipeline not yet started |
| `running` | Pipeline executing: fetching diff, routing, running reviewers |
| `completed` | All reviewers finished; verdict aggregated and posted to GitHub |
| `failed` | Unrecoverable pipeline error (check events for details) |

## Aggregated Verdict Shape

When `status` is `completed`, `aggregated_verdict` contains:

| Field | Type | Description |
|-------|------|-------------|
| `verdict` | string | `PASS`, `WARN`, `FAIL`, or `SKIP` |
| `summary` | string | Human-readable verdict explanation |
| `stats` | object | Reviewer outcome counts: `total`, `pass`, `warn`, `fail`, `skip` |
| `findings_count` | integer | Total deduplicated findings |
| `cost` | object | `total_usd` for the review run |
| `override` | object or null | `{actor, sha}` if overridden, else `null` |

## Verdict Decision Tree

See [Verdict Rules](../README.md#verdict-rules) in the main README for the full decision tree.

## Polling Pattern

The thin GHA action (`api/dispatch.sh`) implements the canonical polling loop:

1. `POST /api/reviews` -> get `review_id`
2. Poll `GET /api/reviews/:id` every `poll-interval` seconds (default: 5)
3. On `completed`: read `aggregated_verdict.verdict`, exit
4. On `failed`: exit with error
5. On timeout (`timeout` seconds, default: 600): exit with SKIP

Consecutive poll errors (non-200) are tolerated up to 10 before aborting.

## Environment Variables

### Server-side (Elixir application)

| Variable | Required | Description |
|----------|----------|-------------|
| `CERBERUS_API_KEY` | yes | Bearer token for API auth |
| `CERBERUS_OPENROUTER_API_KEY` | yes | OpenRouter API key for LLM calls |
| `OPENROUTER_API_KEY` | no | Legacy alias for the above |
| `PORT` | no | HTTP port (default: 4000) |
| `CERBERUS_DB_PATH` | no | SQLite database path |
| `LANGFUSE_PUBLIC_KEY` | no | Langfuse trace export |
| `LANGFUSE_SECRET_KEY` | no | Langfuse trace export |

### Client-side (GHA action)

| Variable / Input | Required | Description |
|------------------|----------|-------------|
| `api-key` | yes | `CERBERUS_API_KEY` value |
| `cerberus-url` | yes | API base URL |
| `model` | no | Model override |
| `timeout` | no | Max wait seconds (default: 600) |
| `poll-interval` | no | Poll interval seconds (default: 5) |
| `fail-on-verdict` | no | Exit 1 on FAIL verdict (default: true) |
