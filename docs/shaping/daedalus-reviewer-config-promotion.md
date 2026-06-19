# Daedalus Reviewer Config Promotion

Snapshot date: 2026-06-18.

Cerberus imports measured reviewer configuration packets. It does not run
Daedalus experiments, self-approve launch gates, or grant production posting
authority.

## Packet Contract

`ReviewerConfigPacket.v1` is the Cerberus-side handoff shape. A valid packet
must include:

- producer identity, generated timestamp, and either a signature or
  `sandbox_only: true`
- benchmark identity, arena version, run id, task count, and score distribution
- promotion gate status plus evidence for G2/G3/G4/G5 or equivalent gates
- rollback metadata pointing at the baseline config
- measured cost and wall-time envelope
- harness, provider, model, prompt hash, and embedded `ReviewConfig.v1`
- `config_hash`, verified as the SHA-256 digest of the embedded
  `ReviewConfig.v1`
- a one-to-one reviewer metadata join: every embedded reviewer must have model
  metadata, every model must point at a known harness, and model/prompt hashes
  must match the embedded config

Unsigned packets are valid only when explicitly sandbox-only. They can be
validated and dry-run, but they must not change production defaults. Signed
non-sandbox packets remain rejected until Cerberus has a configured signature
verification trust path.

## Import Flow

```text
Daedalus measured run or Cerberus eval report
    -> ReviewerConfigPacket.v1
    -> cerberus-cli validate-reviewer-config
    -> cerberus-cli import-reviewer-config --dry-run
    -> ReviewerConfigImportReport.v1
    -> human review before any defaults change
```

`import-reviewer-config --dry-run` compares the packet config against the
current baseline on a clean fixture and records verdict, finding, degraded, and
reviewer/model deltas. The command does not write defaults or caller policy.
Sandbox packets can also drive explicit review runs through
`cerberus-cli review --config-packet <ReviewerConfigPacket.v1>` and
`cerberus-cli review-local --config-packet <ReviewerConfigPacket.v1>`. Those
runs validate the packet and execute its embedded config, but they still do not
approve, install, or mutate production defaults.

Cerberus-owned eval reports use the same packet path through
`cerberus-cli propose-reviewer-config --report <HarnessModelEvaluationReport.v1>
--matrix <HarnessModelMatrix.v1> --suite <EvalTaskSuite.v1> --evidence-dir
<eval-output-dir> --out <ReviewerConfigPacket.v1>`. That bridge only emits
sandbox-only candidate packets from fully passing `live_harness` groups with
full suite coverage and matching transcript artifact envelopes; offline,
unavailable, truncated, or transcript-mismatched reports must fail closed.

## Rejection Rules

- Reject packets whose embedded config hash does not match `config_hash`.
- Reject packets whose reviewer metadata does not match the embedded
  `ReviewConfig.v1`.
- Reject non-sandbox packets until signature verification is configured.
- Reject production import when the promotion status is not `approved`.
- Treat `sandbox_only` packets as importable only for dry-run and sandbox
  experiments.
- Do not treat a raw benchmark win as sufficient promotion evidence.
- Do not let Daedalus own Cerberus posting, GitHub marker, or default rollout
  policy.

## Fixtures

- Packet:
  `fixtures/reviewer-config-packets/daedalus-sandbox-reviewer-config.json`
- Expected dry-run report:
  `fixtures/reviewer-config-packets/daedalus-sandbox-import-report.json`

The fixture packet mirrors Daedalus' G2-accepted, G3-pending
`seed4-qwen3-7-plus-checklist` contract as sandbox-only evidence. It is not a
production recommendation.
