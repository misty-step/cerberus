# Peer Harness Command Profiles

Snapshot date: 2026-06-19.

Backlog 010 introduced peer command profiles for connecting peer harnesses to
the Rust command-adapter path without pretending raw CLIs already implement the
Cerberus input/output protocol. The current packet is
`PeerHarnessCommandProfiles.v3`.

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
- `requires_provider_budget_ack`: whether live execution must require
  `CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK=1`

This keeps `cerberus-core` source-agnostic and keeps subprocess semantics in
adapter land.

## Fixture

`fixtures/harnesses/peer-command-profiles.json` records four profiles:

- Pi: `pi --print --no-session --no-extensions --no-skills --no-context-files --mode text --model openrouter/{model} @{prompt_file}`
- Goose: `goose run --no-session --quiet --provider openrouter --model {model} --instructions {prompt_file}`
- OpenCode: `opencode run --format default --model openrouter/{model} --agent reviewer --file {prompt_file} -- "Follow the attached Cerberus reviewer prompt exactly."`
- OMP: `omp --print --no-session --no-extensions --no-skills --no-rules --mode text --model openrouter/{model} --no-pty @{prompt_file}`

The profile fixture is validation data, not a live model run. Backlog 011 adds
the protocol runner named in the fixture, Backlog 012 adds deterministic prompt
rendering plus exact local transcript fixture parsing, Backlog 015 adds
execution plans, and Backlog 016 adds fixture-backed live command execution.
The OpenRouter-backed profiles remain provider-budget gated. Backlog 017 moves
the checked-in provider templates to private prompt-file transport, but provider
evals still need explicit budget acknowledgement, credentials, and measured
harness/model scoring before any reviewer-default promotion.

After the first provider-backed live smoke on 2026-06-19, the OpenCode profile
was hardened with the `--` separator shown above. Without it, OpenCode's
array-valued `--file` flag consumes the static reviewer instruction as another
file path and fails before model execution. The no-spend receipt at
`tmp/opencode-profile-hardening-2026-06-19/opencode-plan.json`
(`sha256:d551d4d2cf9c6280ce31b7956be949cd805776f726ef45dba25eb8c86d73c15a`)
shows the corrected resolved args; `opencode-separator-probe.txt`
(`sha256:c5c2da713873520d3c9d3923f8e24a9590031d2de0d386b7f4eb9290ec0cea1b`)
reaches the intentionally invalid model lookup instead of the old file error.

A second no-spend hardening pass switched Pi, OpenCode, and OMP away from CLI
JSON event streams and isolated Pi/OMP from locally discovered extensions,
skills, context files, or rules. The strict transcript parser still requires
exactly one marked `ReviewerArtifact.v1` block; the profile change makes the
peer CLIs more likely to emit the assistant response as raw text rather than
tool/event envelopes. This is not provider quality evidence and does not
replace a budget-approved rerun. The no-spend plan receipts are
`tmp/peer-live-profile-output-hardening-2026-06-19/pi-plan.json`
(`sha256:7551ad66c6fffcf11403bf71fdc69919cdd3434c8b252f266004a2676ed62ba8`),
`opencode-plan.json`
(`sha256:f61023010153e2bc54c672e48e148da284b0aaa5cd641dd398d640022ae4fae6`),
and `omp-plan.json`
(`sha256:5d93966a9963a76d92323336f4fe29bfa3fb83566822286797f96ac3ea9ada66`).

## Verification

```bash
cargo test --workspace peer_harness_command_profiles
cargo test --workspace peer_harness_profile_builds_command_harness
cargo run --locked -p cerberus-cli -- validate fixtures/harnesses/peer-command-profiles.json
cargo run --locked -p cerberus-cli -- validate fixtures/harnesses/live-peer-command-profiles.json
```

Offline runner verification lives in
`docs/shaping/peer-harness-protocol-runner.md`. Prompt/transcript fixture proof
lives in `docs/shaping/peer-harness-prompt-transcript.md`. Live acceptance
for the local fixture profile lives in
`docs/shaping/peer-harness-live-invocation.md`. Budget-approved Pi, Goose,
OpenCode, and OMP provider runs remain future eval work even though the
checked-in templates now avoid rendered-prompt argv transport.
