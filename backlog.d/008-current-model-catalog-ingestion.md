# 008 - Current Model Catalog Ingestion

Status: implemented-local-fixture
Priority: P1
Type: epic
Created: 2026-06-18

## Goal

Turn harness/model research facts into a reproducible CLI evidence path.

Backlog 006 proved the eval report shape, but the model candidates in the
matrix are still hand-copied. Cerberus needs a small Rust-owned ingestion step
that reads a raw OpenRouter-compatible model catalog, caches that exact raw
evidence, and refreshes `ModelCandidate.v1` rows before the eval runner grades
any harness/model pair.

## Oracle

`cerberus-cli refresh-model-catalog` can:

- read an existing `HarnessModelMatrix.v1`
- read a raw model catalog from a local file or HTTPS URL
- cache the raw catalog JSON exactly as ingested
- refresh only the matrix model rows requested by the checked-in matrix
- preserve the previous checked matrix facts under each model's `previous`
  snapshot
- write a schema-valid refreshed `HarnessModelMatrix.v1`
- fail clearly when a requested model is missing or a required catalog field is
  unavailable

## Verification System

- `cargo test --workspace model_catalog`
- `cargo run --locked -p cerberus-cli -- refresh-model-catalog --matrix fixtures/evals/harness-model-matrix.json --catalog-source fixtures/evals/openrouter-models-catalog-minimal.json --out tmp/evals/catalog/harness-model-matrix.json --raw-out tmp/evals/catalog/openrouter-models.raw.json --observed-at 2026-06-18`
- `cargo run --locked -p cerberus-cli -- validate tmp/evals/catalog/harness-model-matrix.json`
- `cargo run --locked -p cerberus-cli -- eval-harness --suite fixtures/evals/reviewer-harness-smoke.json --matrix tmp/evals/catalog/harness-model-matrix.json --out tmp/evals/catalog/eval`
- `cargo run --locked -p cerberus-cli -- validate tmp/evals/catalog/eval/report.json`

## Scope

In scope:

- OpenRouter-compatible JSON catalog parser.
- CLI command for file and URL catalog sources.
- Fixture-backed parser tests and command smoke.
- Docs that explain this is catalog ingestion, not live model evaluation.

Out of scope:

- Paid model calls.
- Choosing a production default model.
- Replacing legacy Elixir defaults.
- General provider abstraction beyond the OpenRouter-compatible catalog shape.

## Evidence

- Backlog 006 identified current-model catalog ingestion as the next evidence
  gap after local smoke evaluation.
- The checked matrix currently embeds model facts manually.
- OpenRouter exposes a public model catalog at
  `https://openrouter.ai/api/v1/models`.

## Implementation Receipt

First local delivery, 2026-06-18:

- Added `cerberus-cli refresh-model-catalog`.
- Added an OpenRouter-compatible parser that refreshes checked matrix model
  rows from raw catalog JSON.
- Preserved previous matrix facts under each refreshed model's `previous`
  snapshot.
- Added `fixtures/evals/openrouter-models-catalog-minimal.json` as deterministic
  raw-catalog evidence.
- Proved the refreshed matrix feeds the existing `eval-harness` report path.
