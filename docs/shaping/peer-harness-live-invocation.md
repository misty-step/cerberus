# Peer Harness Live Invocation

Snapshot date: 2026-06-18.

Backlog 016 adds bounded live command invocation to `cerberus-peer-harness`.
This is fixture-backed live execution first: it proves prompt handoff,
subprocess containment, transcript capture, artifact parsing, and provider
budget gating without calling Pi, Goose, OpenCode, OMP, or OpenRouter.

## Contract

With `CERBERUS_PEER_HARNESS_LIVE=1`, the runner:

- validates the selected `PeerHarnessCommandProfiles.v2` packet
- rejects provider-backed profiles unless
  `CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK=1` is set
- rejects provider-backed profiles that pass the rendered prompt through argv
- renders the Cerberus review prompt
- invokes `peer.command` with resolved args under the configured timeout
- sends the prompt through argv or stdin according to `prompt_mode`
- captures stdout as the live transcript
- optionally writes `--transcript-output <path>`
- parses exactly one marked `ReviewerArtifact.v1` JSON block
- validates the artifact against the input reviewer and request

The bounded subprocess helper creates a new process group, kills descendants on
timeout, writes stdin without bypassing the timeout, rejects oversized or
non-UTF-8 stdout transcripts, and keeps stderr diagnostics bounded.

## Fixture Oracle

```bash
mkdir -p tmp
CERBERUS_PEER_HARNESS_LIVE=1 cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- \
  --harness fixture-live \
  --profiles fixtures/harnesses/live-peer-command-profiles.json \
  --input fixtures/harnesses/peer-runner-input.json \
  --output tmp/peer-runner-live-artifact.json \
  --transcript-output tmp/peer-runner-live-transcript.txt

cargo run --locked -p cerberus-cli -- validate \
  tmp/peer-runner-live-artifact.json
```

Passing evidence is a completed `ReviewerArtifact.v1` and a transcript file
containing exactly one begin/end marker pair.

## Provider Boundary

The checked-in Pi, Goose, OpenCode, and OMP profiles have
`requires_provider_budget_ack: true`. They do not run under live mode unless
the operator explicitly sets `CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK=1`.
They also remain blocked while they use argv prompt transport, because the
rendered prompt contains the diff. Budget-approved provider evals with stdin or
private prompt-file transport remain separate harness/model evaluation work.
