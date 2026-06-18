# Peer Harness Command Profiles

Snapshot date: 2026-06-18.

Backlog 010 adds `PeerHarnessCommandProfiles.v1`, a schema for connecting
peer harnesses to the Rust command-adapter path without pretending raw CLIs
already implement the Cerberus input/output protocol.

## Boundary

`CommandHarness` runs a protocol command that accepts:

```text
--input <CommandHarnessInput.json> --output <ReviewerArtifact.v1.json>
```

Pi, Goose, OpenCode, and OMP do not natively share that contract. The checked-in
profile fixture therefore records two layers:

- `command` + `args`: the future `CommandHarness` protocol runner invocation
- `peer.command` + `peer.args_template`: the underlying peer CLI syntax the
  runner should call after it renders a review prompt

This keeps `cerberus-core` source-agnostic and keeps subprocess semantics in
adapter land.

## Fixture

`fixtures/harnesses/peer-command-profiles.json` records four profiles:

- Pi: `pi --print --no-session --mode json --model openrouter/{model} {prompt}`
- Goose: `goose run --no-session --quiet --provider openrouter --model {model} --text {prompt}`
- OpenCode: `opencode run --format json --model openrouter/{model} --agent reviewer {prompt}`
- OMP: `omp --print --no-session --mode json --model openrouter/{model} --no-pty {prompt}`

The profile fixture is validation data, not a live model run. Backlog 011 adds
the protocol runner named in the fixture, and Backlog 012 adds deterministic
prompt rendering plus exact local transcript fixture parsing. Live peer
execution and provider calls remain out of scope.

## Verification

```bash
cargo test --workspace peer_harness_command_profiles
cargo test --workspace peer_harness_profile_builds_command_harness
cargo run --locked -p cerberus-cli -- validate fixtures/harnesses/peer-command-profiles.json
```

Offline runner verification lives in
`docs/shaping/peer-harness-protocol-runner.md`. Prompt/transcript fixture proof
lives in `docs/shaping/peer-harness-prompt-transcript.md`. Live acceptance
later requires peer CLI invocation, transcript capture, eval budget, and parser
evidence from real harness/model runs.
