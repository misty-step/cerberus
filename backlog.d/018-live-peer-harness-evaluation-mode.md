# 018 - Live Peer Harness Evaluation Mode

Status: implemented-local
Priority: P0
Type: feature
Created: 2026-06-19

## Goal

Connect the harness/model evaluation runner to the live peer harness protocol
without spending provider budget by default.

Backlog 017 moved provider peer profiles to private prompt-file transport. This
slice lets `cerberus-cli eval-harness` run eval cells through
`cerberus-peer-harness` in live mode, capture cell evidence, and still fail
closed for provider-backed profiles unless budget acknowledgement and required
environment are present.

## Verification System

- Claim: Cerberus can produce a schema-valid `HarnessModelEvaluationReport.v1`
  from a live peer harness run.
- Falsifier: a live cell is reported as an offline contract result, provider
  profiles can launch without explicit budget/env gates, transcript or
  execution-plan evidence is missing, or eval grading is duplicated outside
  `cerberus-core`.
- Driver: `cerberus-cli eval-harness --execution-mode live-peer`.
- Grader: report validation, `live_harness` cell status, transcript marker and
  prompt-file mode evidence, focused Rust tests, provider fail-closed QA.
- Evidence packet: `tmp/evals/live-peer/`,
  `tmp/evals/live-peer-provider-gated/`, and this backlog receipt.
- Cadence: before any budget-approved Pi, Goose, OpenCode, OMP, or OpenRouter
  harness/model bakeoff.

## Oracle

Cerberus can run:

```bash
CERBERUS_PEER_HARNESS_LIVE=1 cargo run --locked -p cerberus-cli -- eval-harness \
  --execution-mode live-peer \
  --peer-profiles fixtures/harnesses/live-peer-command-profiles.json \
  --suite fixtures/evals/reviewer-harness-live-peer-smoke.json \
  --matrix fixtures/evals/harness-model-live-peer-matrix.json \
  --out tmp/evals/live-peer

cargo run --locked -p cerberus-cli -- validate \
  tmp/evals/live-peer/report.json
```

and receive a valid report containing a `live_harness` pass cell with a valid
reviewer artifact and captured peer transcript.

Provider-backed profiles may be exercised only as fail-closed preflight without
budget or required credentials; they must produce unavailable cells or a
non-zero command before provider invocation, not spend provider budget.

## Scope

In scope:

- CLI `eval-harness --execution-mode live-peer`.
- `--peer-profiles <PeerHarnessCommandProfiles.v3.json>` for live peer runs.
- Core-owned helper for grading externally produced reviewer artifacts into eval
  cells.
- Local live peer eval suite and matrix fixtures.
- Evidence files per live cell: input, reviewer artifact, transcript, and
  execution plan.
- Docs, tests, QA commands, and retirement/backlog updates.

Out of scope:

- Spending provider budget.
- Ranking or promoting harness/model winners.
- Changing reviewer defaults.
- Hosted/API parity.
- Retrying flaky providers.

## Evidence

- `cargo test -p cerberus-core harness_model_eval`
- `cargo check -p cerberus-cli`
- `cargo run --locked -p cerberus-cli -- validate fixtures/evals/reviewer-harness-live-peer-smoke.json fixtures/evals/harness-model-live-peer-matrix.json fixtures/harnesses/live-peer-command-profiles.json`
- `shellcheck fixtures/harnesses/live-peer-reviewer.sh`
- `cargo run --locked -p cerberus-cli -- eval-harness --execution-mode live-peer --peer-profiles fixtures/harnesses/live-peer-command-profiles.json --suite fixtures/evals/reviewer-harness-live-peer-smoke.json --matrix fixtures/evals/harness-model-live-peer-matrix.json --out tmp/evals/live-peer`
- `cargo run --locked -p cerberus-cli -- validate tmp/evals/live-peer/report.json`
- `rg -n '"execution_mode"|"status"|"artifact_valid"|"reviewer_id"|"model"|PROMPT_FILE=|PROMPT_FILE_MODE=600|CERBERUS_REVIEWER_ARTIFACT_JSON_BEGIN|CERBERUS_REVIEWER_ARTIFACT_JSON_END' tmp/evals/live-peer`
- `prompt_path=$(sed -n 's/^PROMPT_FILE=//p' tmp/evals/live-peer/transcripts/fixture-live-file__openrouter_test-model__live-peer-pass.txt); test -n "$prompt_path"; test ! -e "$prompt_path"`
- `jq '.prompt_mode, .resolved_args' tmp/evals/live-peer/plans/fixture-live-file__openrouter_test-model__live-peer-pass.json`
- `env -u CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK -u OPENROUTER_API_KEY cargo run --locked -p cerberus-cli -- eval-harness --execution-mode live-peer --peer-profiles fixtures/harnesses/peer-command-profiles.json --suite fixtures/evals/reviewer-harness-live-peer-smoke.json --matrix fixtures/evals/harness-model-matrix.json --out tmp/evals/live-peer-provider-gated`
- `cargo run --locked -p cerberus-cli -- validate tmp/evals/live-peer-provider-gated/report.json`
- `jq '.summary, ([.cells[] | select(.execution_mode == "live_harness" and .status == "unavailable")] | length), ([.cells[] | select(.status == "pass")] | length)' tmp/evals/live-peer-provider-gated/report.json`
- `find tmp/evals/live-peer-provider-gated/artifacts -type f 2>/dev/null | wc -l`
- `rm -rf tmp/evals/stale-provider && mkdir -p tmp/evals/stale-provider/artifacts tmp/evals/stale-provider/transcripts && cp tmp/evals/reuse-stale/artifacts/fixture-live-file__openrouter_test-model__live-peer-pass.json tmp/evals/stale-provider/artifacts/pi__z-ai_glm-5_2__live-peer-pass.json && cp tmp/evals/reuse-stale/transcripts/fixture-live-file__openrouter_test-model__live-peer-pass.txt tmp/evals/stale-provider/transcripts/pi__z-ai_glm-5_2__live-peer-pass.txt && env -u CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK -u OPENROUTER_API_KEY cargo run --locked -p cerberus-cli -- eval-harness --execution-mode live-peer --peer-profiles fixtures/harnesses/peer-command-profiles.json --suite fixtures/evals/reviewer-harness-live-peer-smoke.json --matrix fixtures/evals/harness-model-matrix.json --out tmp/evals/stale-provider && cargo run --locked -p cerberus-cli -- validate tmp/evals/stale-provider/report.json && test ! -e tmp/evals/stale-provider/artifacts/pi__z-ai_glm-5_2__live-peer-pass.json && rg -n "requires provider budget|live peer eval command failed" tmp/evals/stale-provider/transcripts/pi__z-ai_glm-5_2__live-peer-pass.txt && ! rg -n "Fixture live peer accepted" tmp/evals/stale-provider/transcripts/pi__z-ai_glm-5_2__live-peer-pass.txt`

## Result

`cerberus-cli eval-harness` now accepts
`--execution-mode offline-contract|live-peer`; offline contract remains the
default. Live-peer mode requires `--peer-profiles` and drives
`cerberus-peer-harness` with `CERBERUS_PEER_HARNESS_LIVE=1` for each eval cell.

`cerberus-core` now exposes the shared eval cell grading path for externally
produced reviewer artifacts, so live cells and offline cells use the same
artifact validation, rubric scoring, and report summary logic.

The local live fixture emits a valid `live_harness` pass cell with input,
artifact, transcript, and execution-plan files under `tmp/evals/live-peer`.
The provider-gated preflight over Pi, Goose, OpenCode, and OMP emits 16
`live_harness` unavailable cells, 0 pass cells, and no provider artifacts when
budget acknowledgement is absent. Reused output directories remove stale
per-cell artifacts before each live invocation and overwrite command-failure
transcripts, so a previous success cannot masquerade as a current unavailable
or failed cell. This slice still does not spend provider budget, rank
provider-backed harness/model quality, or promote reviewer defaults.
