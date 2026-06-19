# 019 - Eval Report Reviewer Config Candidate

Status: implemented-local
Priority: P0
Type: feature
Created: 2026-06-19

## Goal

Convert measured harness/model eval evidence into a sandbox-only
`ReviewerConfigPacket.v1` candidate that can flow through the existing Daedalus
promotion import path.

Backlog 018 proved local live peer eval cells. This slice makes the next hop
explicit: report winners can become a reviewable candidate packet, while weak
offline or unavailable reports refuse promotion instead of producing hand-edited
defaults.

## Verification System

- Claim: a schema-valid `HarnessModelEvaluationReport.v1` with a fully passing
  `live_harness` group can produce a schema-valid sandbox-only
  `ReviewerConfigPacket.v1`.
- Falsifier: an offline `warn`, unavailable, degraded, or failed report can
  produce a candidate; a hand-edited pass cell whose embedded artifact fails
  the suite rubric can produce a candidate; an offline report edited to
  `live_harness`/`pass` can produce a candidate without live transcript
  evidence; the packet does not validate; or the generated packet bypasses
  `import-reviewer-config --dry-run` rejection rules.
- Driver: `cerberus-cli propose-reviewer-config --report <report.json>
  --matrix <matrix.json> --suite <suite.json> --evidence-dir <eval-output-dir>
  --out <packet.json>`.
- Grader: packet schema validation, dry-run import report, focused Rust tests,
  and a negative CLI run over provider-gated unavailable cells.
- Evidence packet: `tmp/reviewer-config/eval-live-peer-candidate.json`,
  `tmp/reviewer-config/eval-live-peer-import-report.json`, and this receipt.
- Cadence: after local or provider-backed eval reports and before any defaults
  or Daedalus promotion packet are accepted.

## Oracle

Given the local live-peer fixture report from backlog 018, Cerberus can run:

```bash
cargo run --locked -p cerberus-cli -- propose-reviewer-config \
  --report tmp/evals/live-peer/report.json \
  --matrix fixtures/evals/harness-model-live-peer-matrix.json \
  --suite fixtures/evals/reviewer-harness-live-peer-smoke.json \
  --evidence-dir tmp/evals/live-peer \
  --out tmp/reviewer-config/eval-live-peer-candidate.json

cargo run --locked -p cerberus-cli -- validate-reviewer-config \
  tmp/reviewer-config/eval-live-peer-candidate.json

cargo run --locked -p cerberus-cli -- import-reviewer-config \
  tmp/reviewer-config/eval-live-peer-candidate.json \
  --dry-run \
  --out tmp/reviewer-config/eval-live-peer-import-report.json
```

and receive a valid sandbox-only candidate packet plus a valid dry-run import
report that rejects production import because the packet is not approved.

The same command over an offline-only or provider-gated unavailable eval report
must exit non-zero and leave no candidate packet, including when `--out`
already points at a stale packet.

## Scope

In scope:

- Core-owned conversion from eval report winner to sandbox-only
  `ReviewerConfigPacket.v1`.
- CLI `propose-reviewer-config` command.
- Candidate reviewer defaults for `correctness`, `security`, and `testing`
  using the winning harness/model pair.
- Strict refusal when no fully passing live harness/model group covers the suite.
- Core regrading of every selected report artifact against the supplied suite
  before accepting reported pass fields.
- Live transcript evidence for every selected pass cell, with the transcript
  artifact envelope matching the embedded report artifact.
- Docs, fixtures, tests, QA, and backlog updates.

Out of scope:

- Production approval or default mutation.
- Spending provider budget.
- Daedalus-side export changes.
- Multi-winner ensemble search.
- Semantic prompt synthesis.

## Evidence

- `cargo test -p cerberus-core reviewer_config_candidate`
- `cargo check -p cerberus-cli`
- `cargo run --locked -p cerberus-cli -- eval-harness --execution-mode live-peer --peer-profiles fixtures/harnesses/live-peer-command-profiles.json --suite fixtures/evals/reviewer-harness-live-peer-smoke.json --matrix fixtures/evals/harness-model-live-peer-matrix.json --out tmp/evals/live-peer`
- `cargo run --locked -p cerberus-cli -- propose-reviewer-config --report tmp/evals/live-peer/report.json --matrix fixtures/evals/harness-model-live-peer-matrix.json --suite fixtures/evals/reviewer-harness-live-peer-smoke.json --evidence-dir tmp/evals/live-peer --out tmp/reviewer-config/eval-live-peer-candidate.json`
- `cargo run --locked -p cerberus-cli -- validate-reviewer-config tmp/reviewer-config/eval-live-peer-candidate.json`
- `cargo run --locked -p cerberus-cli -- import-reviewer-config tmp/reviewer-config/eval-live-peer-candidate.json --dry-run --out tmp/reviewer-config/eval-live-peer-import-report.json`
- `cargo run --locked -p cerberus-cli -- validate tmp/reviewer-config/eval-live-peer-import-report.json`
- Offline refusal:
  `cargo run --locked -p cerberus-cli -- eval-harness --suite fixtures/evals/reviewer-harness-smoke.json --matrix fixtures/evals/harness-model-matrix.json --out tmp/evals/harness-model && rm -f tmp/reviewer-config/offline-candidate.json; if cargo run --locked -p cerberus-cli -- propose-reviewer-config --report tmp/evals/harness-model/report.json --matrix fixtures/evals/harness-model-matrix.json --suite fixtures/evals/reviewer-harness-smoke.json --evidence-dir tmp/evals/harness-model --out tmp/reviewer-config/offline-candidate.json; then exit 1; fi; test ! -e tmp/reviewer-config/offline-candidate.json`
- Provider-gated refusal:
  `env -u CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK -u OPENROUTER_API_KEY cargo run --locked -p cerberus-cli -- eval-harness --execution-mode live-peer --peer-profiles fixtures/harnesses/peer-command-profiles.json --suite fixtures/evals/reviewer-harness-live-peer-smoke.json --matrix fixtures/evals/harness-model-matrix.json --out tmp/evals/live-peer-provider-gated && rm -f tmp/reviewer-config/provider-gated-candidate.json; if cargo run --locked -p cerberus-cli -- propose-reviewer-config --report tmp/evals/live-peer-provider-gated/report.json --matrix fixtures/evals/harness-model-matrix.json --suite fixtures/evals/reviewer-harness-live-peer-smoke.json --evidence-dir tmp/evals/live-peer-provider-gated --out tmp/reviewer-config/provider-gated-candidate.json; then exit 1; fi; test ! -e tmp/reviewer-config/provider-gated-candidate.json`
- Stale-output refusal:
  `cp tmp/reviewer-config/eval-live-peer-candidate.json tmp/reviewer-config/stale-refusal.json; if cargo run --locked -p cerberus-cli -- propose-reviewer-config --report tmp/evals/harness-model/report.json --matrix fixtures/evals/harness-model-matrix.json --suite fixtures/evals/reviewer-harness-smoke.json --evidence-dir tmp/evals/harness-model --out tmp/reviewer-config/stale-refusal.json; then exit 1; fi; test ! -e tmp/reviewer-config/stale-refusal.json`

## Result

`cerberus-core` now selects the best fully passing `live_harness` harness/model
group that covers the declared eval suite and constructs a validated
sandbox-only `ReviewerConfigPacket.v1` with an embedded three-reviewer
`ReviewConfig.v1`. Selected pass cells are regraded from their embedded
`ReviewerArtifact.v1` against the supplied suite before packet construction, so
hand-edited report fields cannot promote a failing artifact. Selected cells
must also have live transcript evidence whose artifact envelope matches the
embedded report artifact, so an offline report cannot promote by editing its
mode/status fields to `live_harness`/`pass`.

`cerberus-cli propose-reviewer-config` writes that packet from a report, matrix,
suite, and eval evidence directory. Offline-only `warn` reports and
provider-gated unavailable reports fail closed with no packet output, and stale
output at the requested path is removed before refusal. The generated candidate
validates and imports only as a dry run; production import remains rejected
because the packet is sandbox-only and `candidate`, not `approved`.
