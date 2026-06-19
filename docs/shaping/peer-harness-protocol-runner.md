# Peer Harness Protocol Runner

Snapshot date: 2026-06-18.

Backlog 011 adds the Rust `cerberus-peer-harness` binary used by the
`PeerHarnessCommandProfiles.v2` fixture. It proves the `CommandHarness` file
protocol for peer harnesses, with live command execution restricted to explicit
`CERBERUS_PEER_HARNESS_LIVE=1` runs.

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
- `--profiles <PeerHarnessCommandProfiles.v2.json>`: optional profile packet;
  by default the runner uses `CERBERUS_PEER_HARNESS_PROFILES` or
  `fixtures/harnesses/peer-command-profiles.json`
- `--prompt-output <path>`: optional deterministic prompt output file
- `--transcript <path>`: optional local fixture transcript to parse instead of
  emitting the default degraded artifact
- `--transcript-output <path>`: optional live transcript capture path; requires
  `CERBERUS_PEER_HARNESS_LIVE=1`
- `--execution-plan-output <path>`: optional schema-valid
  `PeerHarnessExecutionPlan.v2` file that records the peer command contract
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

Setting `CERBERUS_PEER_HARNESS_LIVE=1` enables bounded peer command invocation.
The runner renders the review prompt, feeds it through the profile prompt mode,
captures stdout as the transcript, optionally writes `--transcript-output`, and
parses exactly one marked `ReviewerArtifact.v1` JSON block from that transcript.

Profiles with `requires_provider_budget_ack: true` still fail before invocation
unless `CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK=1` is set. The checked-in Pi,
Goose, OpenCode, and OMP profiles require that acknowledgement. The local
`fixture-live` profile does not.

Provider-backed profiles are also refused when they pass the rendered prompt
through argv (`argv_message` or `wrapper_rendered_prompt`). Prompt text includes
the diff, so provider-backed live runs require stdin or a private prompt-file
wrapper before execution.

The execution plan includes command, resolved args, prompt mode, output
contract, timeout, required environment variable names, which required variables
are available or missing, provider-budget acknowledgement status, transcript
markers, and unsupported containment boundaries. It keeps secret values out of
the artifact and leaves `{prompt}` as a placeholder instead of embedding the
rendered review prompt in argv.

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
CERBERUS_PEER_HARNESS_LIVE=1 cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- --harness fixture-live --profiles fixtures/harnesses/live-peer-command-profiles.json --input fixtures/harnesses/peer-runner-input.json --output tmp/peer-runner-live-artifact.json --transcript-output tmp/peer-runner-live-transcript.txt
cargo run --locked -p cerberus-cli -- validate tmp/peer-runner-live-artifact.json
```
