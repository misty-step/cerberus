# Cerberus API Contract

HTTP API for dispatching review runs to the legacy Cerberus Elixir
compatibility engine.

The primary client in this repository is the root GitHub Action:

- `action.yml`
- `cerberus-cli github-action-dispatch`

## Base URL

- Hosted default: `https://cerberus.fly.dev`
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

#### Rust Ingress Fixture

`cerberus-cli hosted-api-ingress-fixture` freezes the legacy POST-body
compatibility contract without starting a server or fetching PR data:

```bash
cargo run --locked -q -p cerberus-cli -- \
  hosted-api-ingress-fixture \
  --body fixtures/hosted-api/create-review-valid.json \
  --out tmp/hosted-api-ingress-2026-06-19/valid.json \
  --review-id 77
```

Accepted reports contain the Elixir-compatible `202` body with integer
`review_id` plus a safe `dispatch_request` pointer. Request-scoped
`github_token` values are never serialized; reports expose only
`github_token_present`. Rejected reports still exit successfully as fixture
evidence and write the legacy `422` error body.

This fixture is not a `ReviewRequest.v1` builder. The POST body is a hosted API
pointer; mapping it to `ReviewRequest.v1` requires a later GitHub acquisition
step that reads PR context, diff, and file metadata.

`cerberus-cli hosted-api-request-fixture` covers that acquisition bridge from
checked inputs:

```bash
cargo run --locked -q -p cerberus-cli -- \
  hosted-api-request-fixture \
  --body fixtures/hosted-api/create-review-valid.json \
  --pr-context fixtures/hosted-api/pull-request-context.json \
  --diff-file fixtures/github-actions/pull-request.diff \
  --out tmp/hosted-api-request-2026-06-19/review-request.json \
  --run-id hosted-api-run-005
```

The command validates the legacy POST body, requires PR-context `head_sha` to
match the POST `head_sha`, parses changed files from the raw diff, and writes a
schema-valid `ReviewRequest.v1`. It still does not perform live GitHub network
IO, run the reviewer engine, persist status, or expose an HTTP server.

### `GET /api/reviews/:id`

Returns the current status and, when complete, the aggregated verdict.

Completed responses may also include a full Rust review artifact under
`review_run_artifact` (abbreviated here):

```json
{
  "status": "completed",
  "aggregated_verdict": { "verdict": "PASS" },
  "review_run_artifact": {
    "schema_version": "review-run-artifact.v1",
    "run_id": "review-run-abc123"
  }
}
```

`cerberus-cli github-action-dispatch` validates the embedded artifact before
using it. If `CERBERUS_ARTIFACT_STORE` is set, completed responses must include
`review_run_artifact`; the CLI persists it through
`FileReviewRunArtifactStore` at `review-runs/<run_id>.json` and fails closed if
the hosted verdict and artifact verdict disagree, or if the artifact
`reviewed_head_sha` does not match the dispatch request `head_sha`. Dispatch
decision JSON and the optional verdict JSON file remain status transcripts and
do not serialize the embedded artifact.

### `GET /api/health`

Simple liveness probe:

```json
{"status":"ok"}
```

## Polling Pattern

`cerberus-cli github-action-dispatch` implements the canonical client loop:

1. Validate fork / draft / missing-input preconditions.
2. `POST /api/reviews`.
3. Poll `GET /api/reviews/:id` every `poll-interval` seconds.
4. Emit `verdict` and `review-id` outputs.
5. Exit non-zero on API failure or configured failing verdict.

## Action Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `api-key` | yes | - | API auth token |
| `cerberus-url` | no | `https://cerberus.fly.dev` | API base URL override for self-hosted or non-default deployments |
| `github-token` | no | `''` | GitHub token forwarded to the hosted Cerberus pipeline for per-request PR reads and writes |
| `model` | no | `''` | Reserved model override |
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

| Variable / input | Required | Description |
|-------|----------|-------------|
| `api-key` | yes | `CERBERUS_API_KEY` value |
| `cerberus-url` | no | Optional API base URL override; defaults to `https://cerberus.fly.dev` |
| `github-token` | no | Optional request-scoped GitHub token forwarded in `POST /api/reviews` |
| `CERBERUS_ARTIFACT_STORE` | no | Optional local directory where the action dispatcher persists completed `ReviewRunArtifact.v1` payloads when the hosted API returns them |
