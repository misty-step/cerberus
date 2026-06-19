# 027 - Eval Readiness Report

Status: implemented
Priority: P0
Type: feature
Created: 2026-06-19

## Goal

Add a Rust-owned preflight report for provider-backed harness/model evals.
Cerberus should be able to tell an operator which Pi, Goose, OpenCode, and OMP
eval cells are runnable in the current environment, which cells are blocked by
missing harnesses, live peer runners, profiles, required environment, or
provider-budget acknowledgement, and which suite/matrix ids and peer-profile
observation stamp fed the check.

This moves provider evals forward without spending model budget or promoting
defaults.

## Verification System

- Claim: `cerberus-cli eval-readiness` writes a schema-valid
  `EvalReadinessReport.v1` from an eval suite, harness/model matrix, and peer
  harness profiles.
- Falsifier: provider-backed cells are reported runnable without required env,
  live peer-runner availability, or budget acknowledgement, missing
  harness/profile blockers are hidden, the report cannot be validated, or the
  command invokes paid provider harnesses.
- Driver:
  - `cargo run --locked -p cerberus-cli -- eval-readiness --suite ... --matrix ... --peer-profiles ... --out ...`
  - `cargo run --locked -p cerberus-cli -- validate <readiness-report.json>`
- Grader: focused Rust tests over runnable and blocked cells, schema validation,
  JSON assertions over summary counts and blockers, and evidence that no
  provider artifacts are written.
- Evidence packet: `tmp/evals/provider-readiness-2026-06-19/`.
- Cadence: before every provider-backed `eval-harness --execution-mode
  live-peer` run and before reviewer config promotion from provider results.

## Scope

In scope:

- `EvalReadinessReport.v1` schema.
- Core-owned readiness computation from suite, matrix, harness probes, live
  peer-runner probes, peer profiles, visible env names, and budget
  acknowledgement.
- CLI `eval-readiness`.
- Backlog sequence, docs, plan, QA evidence, and tests.
- Dated current model/harness evidence for the checked matrix.

Out of scope:

- Spending provider budget.
- Ranking provider-backed winners.
- Changing reviewer defaults.
- Fetching secrets or modifying local harness auth.
- Replacing the existing live-peer eval runner.

## Evidence

- Plan: `docs/shaping/027-eval-readiness-report-plan.html`
- Live source snapshot:
  `tmp/evals/provider-readiness-2026-06-19/openrouter-models-live.json`
- Harness version snapshot:
  `tmp/evals/provider-readiness-2026-06-19/harness-versions.txt`
- Blocked readiness report:
  `tmp/evals/provider-readiness-2026-06-19/readiness-no-env.json`
- Runnable readiness report with fake env and budget acknowledgement:
  `tmp/evals/provider-readiness-2026-06-19/readiness-env-ack.json`
- Focused tests:
  - `cargo test -p cerberus-schema eval_readiness_report`
  - `cargo test -p cerberus-core harness_model_readiness`
- CLI QA:
  - `env -u OPENROUTER_API_KEY -u CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK cargo run --locked -q -p cerberus-cli -- eval-readiness --suite fixtures/evals/reviewer-harness-live-peer-smoke.json --matrix fixtures/evals/harness-model-matrix.json --peer-profiles fixtures/harnesses/peer-command-profiles.json --out tmp/evals/provider-readiness-2026-06-19/readiness-no-env.json`
  - `cargo run --locked -q -p cerberus-cli -- validate tmp/evals/provider-readiness-2026-06-19/readiness-no-env.json`
  - `OPENROUTER_API_KEY=dummy CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK=1 cargo run --locked -q -p cerberus-cli -- eval-readiness --suite fixtures/evals/reviewer-harness-live-peer-smoke.json --matrix fixtures/evals/harness-model-matrix.json --peer-profiles fixtures/harnesses/peer-command-profiles.json --out tmp/evals/provider-readiness-2026-06-19/readiness-env-ack.json`
  - `cargo run --locked -q -p cerberus-cli -- validate tmp/evals/provider-readiness-2026-06-19/readiness-env-ack.json`

## Result

Implemented. `cerberus-schema` now defines `EvalReadinessReport.v1`, and
`cerberus-core` computes readiness from the eval suite, harness/model matrix,
harness probes, live peer-runner probes, peer harness profiles, visible required
env names, and provider budget acknowledgement. `cerberus-cli eval-readiness`
writes that report without invoking provider harnesses.

With `OPENROUTER_API_KEY` and
`CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK` absent in this environment, the
checked provider matrix reports 16 total cells, 0 runnable cells, 16 missing-env
cells, and 16 budget-blocked cells. With a dummy `OPENROUTER_API_KEY` and budget
acknowledgement set, the same preflight reports all 16 cells runnable. This is
readiness evidence only; it does not rank models, spend budget, promote
defaults, or prove provider-backed review quality.
