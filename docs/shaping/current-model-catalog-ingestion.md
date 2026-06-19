# Current Model Catalog Ingestion

Snapshot date: 2026-06-19.

Backlog 008 adds the evidence bridge between model research and the harness
evaluation matrix. Model facts should enter Cerberus through a cached raw
catalog and a checked transformation, not hand-edited prose.

## Command

```bash
cargo run --locked -p cerberus-cli -- refresh-model-catalog \
  --matrix fixtures/evals/harness-model-matrix.json \
  --catalog-source fixtures/evals/openrouter-models-catalog-minimal.json \
  --out tmp/evals/catalog/harness-model-matrix.json \
  --raw-out tmp/evals/catalog/openrouter-models.raw.json \
  --observed-at 2026-06-19T05:46:00Z
```

`--catalog-source` accepts a local file or an `http://` / `https://` URL. URL
mode is an operator convenience for live OpenRouter refreshes; fixture mode is
the deterministic local gate. URL mode uses the local `curl` binary and fails
before writing derived output if the fetch cannot complete.

## Contract

The command:

- reads a schema-valid `HarnessModelMatrix.v1`
- ingests an OpenRouter-compatible catalog JSON document
- writes the raw catalog bytes to `--raw-out`
- refreshes only the model IDs already requested by the matrix
- stores the previous checked matrix facts under each model's `previous`
  snapshot
- writes a schema-valid refreshed matrix to `--out`

It fails if a requested model is absent or required fields such as prompt price,
completion price, context length, or max completion tokens are unavailable.

Backlog 022 refreshed the tiny catalog against the live OpenRouter API on
2026-06-19. The current checked fixture records GLM 5.2 output price `$4.10/M`
and max completion `131,072`, with the 2026-06-18 `$3.20/M` / `65,536` values
kept in the matrix's previous snapshot.

## Follow-On Proof

The refreshed matrix is not itself a model-quality verdict. It is input evidence
for:

```bash
cargo run --locked -p cerberus-cli -- eval-harness \
  --suite fixtures/evals/reviewer-harness-smoke.json \
  --matrix tmp/evals/catalog/harness-model-matrix.json \
  --out tmp/evals/catalog/eval
```

Production defaults still require live harness/model transcripts and review
quality grading before promotion.
