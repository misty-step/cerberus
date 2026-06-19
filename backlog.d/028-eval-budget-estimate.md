# 028 - Eval Budget Estimate

Status: implemented
Priority: P0
Type: feature
Created: 2026-06-19

## Goal

Add a Rust-owned no-spend budget estimate before provider-backed peer evals.
Cerberus should be able to turn a readiness report, checked model matrix, and
explicit token assumptions into a reviewable cost envelope before an operator
sets `CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK`.

This closes the gap between "the cells are ready except for budget ack" and
"the operator knows what budget is being acknowledged."

## Verification System

- Claim: `cerberus-cli eval-budget` writes a schema-valid
  `EvalBudgetEstimateReport.v1` without invoking provider harnesses.
- Falsifier: totals drift from cell costs, readiness suite/matrix ids do not
  match the checked inputs, readiness coverage omits suite/matrix cells,
  non-runnable infrastructure blockers are hidden, or the command can imply
  quality/ranking instead of cost exposure.
- Driver:
  - `cargo run --locked -p cerberus-cli -- eval-budget --suite ... --matrix ... --readiness ... --prompt-tokens ... --completion-tokens ... --out ...`
  - `cargo run --locked -p cerberus-cli -- validate <budget-report.json>`
- Grader: schema validation, focused Rust tests over cost math and mismatch
  rejection, CLI QA over the current readiness report, and evidence that no
  provider artifacts/transcripts are written.
- Evidence packet: `tmp/evals/provider-budget-2026-06-19/`.
- Cadence: after `eval-readiness`, before setting
  `CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK` for provider-backed evals.

## Scope

In scope:

- `EvalBudgetEstimateReport.v1` schema.
- Core-owned cost estimation from suite, matrix, readiness cells, explicit
  prompt/completion token assumptions, and retry count.
- CLI `eval-budget`.
- Backlog sequence, docs, plan, QA evidence, and tests.

Out of scope:

- Spending provider budget.
- Guessing real token usage from prompts.
- Ranking provider-backed winners.
- Changing reviewer defaults.
- Launching provider harnesses.

## Evidence

- Plan: `docs/shaping/028-eval-budget-estimate-plan.html`
- Readiness artifact:
  `tmp/evals/provider-budget-2026-06-19/readiness-no-ack.json`
- Budget estimate artifact:
  `tmp/evals/provider-budget-2026-06-19/budget-estimate.json`
- QA assumptions: `20000` prompt tokens, `4000` completion tokens, `1` retry
  per cell.
- QA summary: 16 total cells, 16 estimateable cells, 0 blocked cells,
  estimated total cost `$0.3356`, max single-cell cost `$0.0404`.

## Result

Implemented. `cerberus-cli eval-budget` writes a schema-valid
`EvalBudgetEstimateReport.v1` from the checked suite, checked matrix,
readiness report, and explicit token/retry assumptions. The generated evidence
packet contains only readiness and budget JSON files, so this preflight does
not invoke provider harnesses, write transcripts, rank models, or promote
defaults. The core rejects readiness reports that do not cover the full checked
suite/matrix cell set, and budget cells carry structured readiness state so
estimateability does not depend on parsing blocker prose.
