# Peer Harness Execution Plan

Snapshot date: 2026-06-19.

Backlog 015 introduced `cerberus-peer-harness --execution-plan-output <path>`.
The current packet is `PeerHarnessExecutionPlan.v3`. This makes the live peer
harness contract inspectable before Cerberus is allowed to execute Pi, Goose,
OpenCode, OMP, OpenRouter, or any paid provider.

## Contract

The plan records:

- selected harness id and peer command
- resolved peer args with `{model}` replaced and the prompt represented by the
  active prompt mode: `{prompt}`, `{prompt_file}`, or stdin omission
- prompt mode and output contract
- timeout and unsupported containment boundaries
- required environment variable names, split into available and missing names
- whether provider-budget acknowledgement is required and currently present
- transcript begin/end markers
- whether live mode was requested

The artifact never records secret values and does not embed the rendered prompt.

## Live Mode Boundary

`CERBERUS_PEER_HARNESS_LIVE=1` can execute fixture-backed peer profiles after
Backlog 016. OpenRouter-backed profiles still require
`CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK=1` before live execution. Backlog
017 moves the checked-in provider profiles to `prompt_file`; if budget
acknowledgement or required credentials are missing, the runner may write the
plan with `live_mode_requested: true`, then exits before producing a reviewer
artifact or launching the peer command.

## Verification

```bash
cargo test --workspace peer_harness_execution_plan
cargo test -p cerberus-cli --test peer_harness_command
mkdir -p tmp
cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- --harness pi --input fixtures/harnesses/peer-runner-input.json --output tmp/peer-runner-artifact.json --execution-plan-output tmp/peer-runner-execution-plan.json
cargo run --locked -p cerberus-cli -- validate tmp/peer-runner-execution-plan.json
env -u CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK CERBERUS_PEER_HARNESS_LIVE=1 cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- --harness pi --input fixtures/harnesses/peer-runner-input.json --output tmp/peer-runner-live-artifact.json --execution-plan-output tmp/peer-runner-live-plan.json
env -u OPENROUTER_API_KEY CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK=1 CERBERUS_PEER_HARNESS_LIVE=1 cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- --harness pi --input fixtures/harnesses/peer-runner-input.json --output tmp/peer-runner-live-artifact.json --execution-plan-output tmp/peer-runner-live-plan.json
```

The final two commands are expected to return non-zero without spending
provider budget: first for missing budget acknowledgement, then for missing
provider credentials with budget explicitly acknowledged. Passing evidence is
`tmp/peer-runner-live-plan.json` existing, `prompt_mode: "prompt_file"`, and
`tmp/peer-runner-live-artifact.json` not existing.
