# Peer Harness Execution Plan

Snapshot date: 2026-06-18.

Backlog 015 adds `PeerHarnessExecutionPlan.v1` and
`cerberus-peer-harness --execution-plan-output <path>`. This makes the live peer
harness contract inspectable before Cerberus is allowed to execute Pi, Goose,
OpenCode, OMP, OpenRouter, or any paid provider.

## Contract

The plan records:

- selected harness id and peer command
- resolved peer args with `{model}` replaced and `{prompt}` left as a
  placeholder
- prompt mode and output contract
- timeout and unsupported containment boundaries
- required environment variable names, split into available and missing names
- transcript begin/end markers
- whether live mode was requested

The artifact never records secret values and does not embed the rendered prompt.

## Live Mode Boundary

`CERBERUS_PEER_HARNESS_LIVE=1` still fails closed. If
`--execution-plan-output` is present, the runner writes the plan with
`live_mode_requested: true`, then exits before producing a reviewer artifact or
launching the peer command.

## Verification

```bash
cargo test --workspace peer_harness_execution_plan
cargo test -p cerberus-cli --test peer_harness_command
mkdir -p tmp
cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- --harness pi --input fixtures/harnesses/peer-runner-input.json --output tmp/peer-runner-artifact.json --execution-plan-output tmp/peer-runner-execution-plan.json
cargo run --locked -p cerberus-cli -- validate tmp/peer-runner-execution-plan.json
CERBERUS_PEER_HARNESS_LIVE=1 cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- --harness pi --input fixtures/harnesses/peer-runner-input.json --output tmp/peer-runner-live-artifact.json --execution-plan-output tmp/peer-runner-live-plan.json
```

The final command is expected to return non-zero. Passing evidence is
`tmp/peer-runner-live-plan.json` existing and
`tmp/peer-runner-live-artifact.json` not existing.
