# 014 - Current Harness Model Catalog Refresh

Status: done
Priority: P0
Type: epic
Created: 2026-06-18

## Goal

Refresh Cerberus's checked harness/model evaluation matrix from current
primary-source evidence before any live harness/model bake-off or production
default promotion.

This ticket exists because the model and harness facts are drift-prone:
OpenRouter model limits/pricing and local harness versions can change within
the same day. The matrix must carry dated evidence and previous snapshots so
later eval and Daedalus promotion decisions are reviewable.

## Oracle

Cerberus can run:

```bash
cargo run --locked -p cerberus-cli -- validate \
  fixtures/evals/harness-model-matrix.json

cargo run --locked -p cerberus-cli -- eval-harness \
  --suite fixtures/evals/reviewer-harness-smoke.json \
  --matrix fixtures/evals/harness-model-matrix.json \
  --out tmp/evals/harness-model

cargo run --locked -p cerberus-cli -- validate \
  tmp/evals/harness-model/report.json
```

and receive a schema-valid offline eval report whose matrix reflects the current
OpenRouter and local harness facts recorded in this ticket.

## Verification System

- Primary-source refresh:
  `curl -fsSL https://openrouter.ai/api/v1/models`
- Local harness probe:
  `command -v pi goose opencode omp` and each `--version`
- `cargo test --workspace model_catalog`
- `jq empty` for the raw OpenRouter catalog fixture
- `cerberus-cli validate` for the refreshed matrix and eval report
- offline `eval-harness` smoke using the refreshed matrix
- full repo gates continue to pass

## Scope

In scope:

- Update `fixtures/evals/harness-model-matrix.json`.
- Update `fixtures/evals/openrouter-models-catalog-minimal.json`.
- Record current OMP, GLM 5.2, Kimi K2.7 Code, and DeepSeek V4 facts.
- Preserve previous model facts as drift evidence.
- Add focused automated coverage for the GLM 5.2 drift in the refresh path.
- Update eval docs and backlog sequencing.

Out of scope:

- Running paid live harness/model cells.
- Promoting production defaults.
- Ranking Pi, Goose, OpenCode, or OMP as a winner.
- Changing legacy Elixir defaults.
- Replacing OpenRouter with first-party provider clients.

## Research Snapshot

Snapshot date: 2026-06-18.

- Firecrawl search was attempted first, but the account returned HTTP 402. The
  fallback evidence is direct OpenRouter API retrieval plus official-source web
  pages.
- Local harness versions:
  - `pi` 0.78.1
  - `goose` 1.12.1
  - `opencode` 1.2.6
  - `omp` 16.0.9
- OpenRouter API current facts:
  - `z-ai/glm-5.2`: context 1,048,576; top-provider context 202,752;
    max completion 65,536; input $1.20/M; output $3.20/M; cache read $0.20/M.
  - `moonshotai/kimi-k2.7-code`: context 262,144; max completion 16,384;
    input $0.74/M; output $3.50/M; cache read $0.15/M.
  - `deepseek/deepseek-v4-pro`: context 1,048,576; max completion 384,000;
    input $0.435/M; output $0.87/M; cache read $0.003625/M.
  - `deepseek/deepseek-v4-flash`: model context 1,048,576; top-provider
    context 1,000,000; max completion 65,536; input $0.09/M; output $0.18/M;
    cache read $0.02/M.

## Evidence

- Plan: `docs/shaping/014-current-harness-model-catalog-refresh-plan.html`
- OpenRouter API: `https://openrouter.ai/api/v1/models`
- GLM 5.2 model page: `https://openrouter.ai/z-ai/glm-5.2/api`
- Kimi K2.7 Code docs:
  `https://platform.kimi.ai/docs/guide/kimi-k2-7-code-quickstart`
- DeepSeek V4 preview:
  `https://api-docs.deepseek.com/news/news260424`
- DeepSeek pricing:
  `https://api-docs.deepseek.com/quick_start/pricing`
- Goose docs: `https://goose-docs.ai/`
- OpenCode OpenRouter docs:
  `https://openrouter.ai/docs/cookbook/coding-agents/opencode-integration`
- Pi docs: `https://pi.dev/`
- OMP README: `https://github.com/can1357/oh-my-pi`

## Implementation Receipt

First local delivery, 2026-06-18:

- Refreshed `fixtures/evals/openrouter-models-catalog-minimal.json` from the
  live OpenRouter API rows for GLM 5.2, Kimi K2.7 Code, DeepSeek V4 Pro, and
  DeepSeek V4 Flash.
- Updated `fixtures/evals/harness-model-matrix.json` with OMP `16.0.9`, GLM
  5.2 max completion `65,536`, GLM 5.2 output `$3.20/M`, and full supported
  parameter lists.
- Preserved previous model facts inside the matrix so the offline eval report
  records GLM 5.2 deltas from `16,384` to `65,536` max completion and
  `$4.20/M` to `$3.20/M` output.
- Added focused `model_catalog` assertions for the checked GLM 5.2 previous
  snapshot and refresh behavior.
- Updated backlog, docs index, catalog-ingestion docs, and harness/model eval
  docs with the refreshed current evidence and Firecrawl 402 fallback note.
- Verified with:
  - `command -v pi goose opencode omp`
  - `pi --version`
  - `goose --version`
  - `opencode --version`
  - `omp --version`
  - `curl -fsSL https://openrouter.ai/api/v1/models -o tmp/openrouter-models-live.json`
  - `jq empty fixtures/evals/harness-model-matrix.json fixtures/evals/openrouter-models-catalog-minimal.json`
  - `cargo test --workspace model_catalog`
  - `cargo run --locked -p cerberus-cli -- validate fixtures/evals/harness-model-matrix.json`
  - `cargo run --locked -p cerberus-cli -- refresh-model-catalog --matrix fixtures/evals/harness-model-matrix.json --catalog-source fixtures/evals/openrouter-models-catalog-minimal.json --out tmp/evals/catalog/harness-model-matrix.json --raw-out tmp/evals/catalog/openrouter-models.raw.json --observed-at 2026-06-18T18:20:00Z`
  - `cargo run --locked -p cerberus-cli -- validate tmp/evals/catalog/harness-model-matrix.json`
  - `cargo run --locked -p cerberus-cli -- eval-harness --suite fixtures/evals/reviewer-harness-smoke.json --matrix fixtures/evals/harness-model-matrix.json --out tmp/evals/harness-model`
  - `cargo run --locked -p cerberus-cli -- validate tmp/evals/harness-model/report.json`
  - `cargo fmt --all -- --check`
  - `git diff --check`

Offline eval result:

- 64 total cells
- 64 valid artifacts
- 48 warning cells
- 16 degraded cells
- 0 failed cells
- 27 stale-model findings
- GLM 5.2 catalog deltas for max completion and output price
