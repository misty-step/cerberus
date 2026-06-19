# 022 - Current Model Catalog Drift Refresh

Status: implemented
Priority: P0
Type: maintenance
Created: 2026-06-19

## Goal

Refresh the checked harness/model matrix after live OpenRouter evidence drifted
from the 2026-06-18 snapshot. The evaluation loop should consume dated model
facts, not stale pricing or context limits, before any paid harness/model run or
reviewer-default promotion.

This is a repeatable evidence slice, not a model-quality bake-off.

## Verification System

- Claim: the checked catalog fixture and `HarnessModelMatrix.v1` reflect the
  current OpenRouter rows for GLM 5.2, Kimi K2.7 Code, DeepSeek V4 Pro, and
  DeepSeek V4 Flash, while preserving the prior checked facts as drift evidence.
- Falsifier: `refresh-model-catalog` emits different candidate rows from the
  checked fixture, GLM 5.2 drift disappears from `previous`, matrix/report
  validation fails, or the change promotes models without live eval evidence.
- Driver:
  `cerberus-cli refresh-model-catalog --matrix <matrix> --catalog-source https://openrouter.ai/api/v1/models --out <matrix> --raw-out <raw>`.
- Grader: schema validation, focused `model_catalog` tests, offline
  `eval-harness` report validation, and fresh critic review.
- Evidence packet: `tmp/evals/catalog-refresh-2026-06-19/`.
- Cadence: before provider spend, reviewer config promotion, or any time the
  OpenRouter catalog changes the requested candidate rows.

## Scope

In scope:

- Refresh `fixtures/evals/openrouter-models-catalog-minimal.json`.
- Refresh `fixtures/evals/harness-model-matrix.json`.
- Preserve previous checked model facts in each matrix row.
- Tighten catalog price conversion so checked JSON does not carry floating-point
  noise as fake provider drift.
- Update docs, backlog sequence, and tests.

Out of scope:

- Running paid live provider cells.
- Ranking Pi, Goose, OpenCode, or OMP.
- Promoting reviewer defaults.
- Changing legacy Elixir model defaults.
- Replacing OpenRouter as the catalog source.

## Current Evidence

Local harness probes on 2026-06-19:

- `pi` 0.78.1
- `goose` 1.12.1
- `opencode` 1.2.6
- `omp` 16.0.9

OpenRouter API rows observed at `2026-06-19T05:46:00Z`:

| Model id | Context | Top-provider context | Max completion | Input $/M | Output $/M | Cache read $/M |
|---|---:|---:|---:|---:|---:|---:|
| `z-ai/glm-5.2` | 1,048,576 | 1,048,576 | 131,072 | 1.20 | 4.10 | 0.20 |
| `moonshotai/kimi-k2.7-code` | 262,144 | 262,144 | 16,384 | 0.74 | 3.50 | 0.15 |
| `deepseek/deepseek-v4-pro` | 1,048,576 | 1,048,576 | 384,000 | 0.435 | 0.87 | 0.003625 |
| `deepseek/deepseek-v4-flash` | 1,048,576 | 1,000,000 | 65,536 | 0.09 | 0.18 | 0.02 |

Compared to the checked 2026-06-18 matrix, GLM 5.2 changed from max completion
`65,536` to `131,072`, top-provider context `202,752` to `1,048,576`, and
output price `$3.20/M` to `$4.10/M`.

## Evidence

- Plan: `docs/shaping/022-current-model-catalog-drift-refresh-plan.html`
- Source: `https://openrouter.ai/api/v1/models`
- Generated raw/source packet:
  `tmp/evals/catalog-refresh-2026-06-19/openrouter-models.live.json`
- Focused tests:
  `cargo test --workspace model_catalog`
- Fixture validation:
  `jq empty fixtures/evals/harness-model-matrix.json fixtures/evals/openrouter-models-catalog-minimal.json`
- Matrix validation:
  `cargo run --locked -p cerberus-cli -- validate fixtures/evals/harness-model-matrix.json`
- Refresh QA:
  `cargo run --locked -p cerberus-cli -- refresh-model-catalog --matrix fixtures/evals/harness-model-matrix.json --catalog-source fixtures/evals/openrouter-models-catalog-minimal.json --out tmp/evals/catalog-refresh-2026-06-19/qa-matrix.json --raw-out tmp/evals/catalog-refresh-2026-06-19/qa-openrouter.raw.json --observed-at 2026-06-19T05:46:00Z`
  preserves GLM 5.2 `previous.max_completion_tokens = 65,536` and
  `previous.output_usd_per_m = 3.20` on a no-op refresh from the current matrix.
- Offline eval QA:
  `cargo run --locked -p cerberus-cli -- eval-harness --suite fixtures/evals/reviewer-harness-smoke.json --matrix fixtures/evals/harness-model-matrix.json --out tmp/evals/catalog-refresh-2026-06-19/eval`
  emits report `2026-06-19-openrouter-smoke-reviewer-harness-smoke` with 64
  cells, 64 valid artifacts, 48 warn cells, 16 degraded cells, and 0 failures.
- Fresh critic: found one blocking QA gap where repeated refreshes overwrote
  `previous` and erased GLM drift evidence. Fixed by making
  `refresh-model-catalog` retain the existing `previous` snapshot when tracked
  model facts are unchanged, with focused test coverage for both stale and
  no-op refresh paths.
- Fresh critic re-review: no blockers; confirmed the prior blocker was resolved
  and no paid eval, default promotion, model ranking, or legacy default change
  entered the diff.

## Result

Implemented. The checked matrix now records the 2026-06-19 OpenRouter snapshot
and keeps the 2026-06-18 GLM 5.2 values under `previous`. The catalog refresh
path is idempotent for unchanged model facts and rounds derived USD-per-million
values to avoid noisy JSON drift. No live provider evals or reviewer defaults
changed.

No-op freshness check, 2026-06-19T11:36:40Z:

- Direct refresh from `https://openrouter.ai/api/v1/models` wrote
  `tmp/evals/catalog-refresh-2026-06-19-current/harness-model-matrix.url-generated.json`
  and validated it successfully.
- The generated matrix was semantically equal to
  `fixtures/evals/harness-model-matrix.json` after normalizing only
  `observed_at` and `catalog_observed_at`.
- Raw OpenRouter evidence:
  `tmp/evals/catalog-refresh-2026-06-19-current/openrouter-models.url.raw.json`
  (`sha256:d1a67c59601069540f5e4c87a5f436f9ae0666e2b2f061e44f9a632771dac009`).
- Generated matrix:
  `sha256:71eb883b260c268808fca790d532379ad7decb1f0104b540bf9153c2fcad6325`.
- No checked fixture rewrite was needed; the remaining backlog 006 gate is
  provider budget acknowledgement plus a full six-task live rerun, not catalog
  drift.
