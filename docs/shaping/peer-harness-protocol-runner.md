# Peer Harness Protocol Runner

Snapshot date: 2026-06-18.

Backlog 011 adds the Rust `cerberus-peer-harness` binary used by the
`PeerHarnessCommandProfiles.v1` fixture. It proves the `CommandHarness` file
protocol for peer harnesses while intentionally refusing live model execution.

## Contract

```bash
cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- \
  --harness pi \
  --input fixtures/harnesses/peer-runner-input.json \
  --output tmp/peer-runner-artifact.json
```

The binary accepts:

- `--harness <id>`: one of the validated profile harness ids
- `--input <CommandHarnessInput.json>`: reviewer plus request envelope written
  by `CommandHarness`
- `--output <ReviewerArtifact.v1.json>`: output file to write
- `--profiles <PeerHarnessCommandProfiles.v1.json>`: optional profile packet;
  by default the runner uses `CERBERUS_PEER_HARNESS_PROFILES` or
  `fixtures/harnesses/peer-command-profiles.json`
- `--prompt-output <path>`: optional deterministic prompt output file
- `--transcript <path>`: optional local fixture transcript to parse instead of
  emitting the default degraded artifact
- `--execution-plan-output <path>`: optional schema-valid
  `PeerHarnessExecutionPlan.v1` file that records the peer command contract
  without invoking the peer harness

## Offline Artifact

Without `--transcript`, the runner writes a degraded artifact:

- reviewer id, perspective, and model come from the input reviewer
- `coverage.files_reviewed` exactly matches the request files
- findings are empty
- `status` is `degraded`
- `verdict` is `SKIP`
- usage and cost are zero
- `degraded_reason` states that live peer execution is disabled

This is a protocol proof, not a review-quality proof.

With `--transcript`, the runner parses exactly one marked
`ReviewerArtifact.v1` JSON block from the local transcript fixture and validates
it against the input reviewer and request through `cerberus-core`.

## Live Execution Guard

Setting `CERBERUS_PEER_HARNESS_LIVE=1` fails closed. When
`--execution-plan-output` is present, the runner writes the execution plan first
with `live_mode_requested: true`, then exits before writing a reviewer artifact
or invoking Pi, Goose, OpenCode, OMP, OpenRouter, or any paid provider.

The plan includes command, resolved args, prompt mode, output contract, timeout,
required environment variable names, which required variables are available or
missing, transcript markers, and unsupported containment boundaries. It keeps
secret values out of the artifact and leaves `{prompt}` as a placeholder instead
of embedding the rendered review prompt in argv.

## Verification

```bash
cargo test --workspace peer_harness_runner
cargo test -p cerberus-cli --test peer_harness_command
mkdir -p tmp
cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- --harness pi --input fixtures/harnesses/peer-runner-input.json --output tmp/peer-runner-artifact.json
cargo run --locked -p cerberus-cli -- validate tmp/peer-runner-artifact.json
cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- --harness pi --input fixtures/harnesses/peer-runner-input.json --output tmp/peer-runner-transcript-artifact.json --prompt-output tmp/peer-runner-prompt.txt --transcript fixtures/harnesses/peer-transcript-with-finding.txt
cargo run --locked -p cerberus-cli -- validate tmp/peer-runner-transcript-artifact.json
cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- --harness pi --input fixtures/harnesses/peer-runner-input.json --output tmp/peer-runner-artifact.json --execution-plan-output tmp/peer-runner-execution-plan.json
cargo run --locked -p cerberus-cli -- validate tmp/peer-runner-execution-plan.json
```
