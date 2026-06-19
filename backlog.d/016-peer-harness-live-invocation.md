# 016 - Peer Harness Live Invocation

Status: implemented-local
Priority: P0
Type: epic
Created: 2026-06-18

## Goal

Make `cerberus-peer-harness` capable of executing a peer command under an
explicit live flag while keeping provider spend and unbounded subprocess output
guarded.

Backlog 015 made the live command inspectable as data. This slice makes the
same contract executable for fixture-backed peer commands first, then leaves
paid provider profiles behind an explicit budget acknowledgement.

## Verification System

- Claim: Cerberus can run a configured peer command, feed it the rendered review
  prompt, capture its transcript, parse the marked `ReviewerArtifact.v1`, and
  write a validated artifact.
- Falsifier: live mode invokes a provider profile without explicit budget
  acknowledgement, leaves descendants running after timeout, loses the
  transcript, accepts malformed output, or writes a reviewer artifact after a
  peer failure.
- Driver: `CERBERUS_PEER_HARNESS_LIVE=1 cerberus-peer-harness --harness
  fixture-live --profiles fixtures/harnesses/live-peer-command-profiles.json`.
- Grader: focused Rust tests, transcript-output existence and contents,
  `cerberus-cli validate <artifact>`, timeout tests, and full repo gates.
- Evidence packet: `tmp/peer-runner-live-artifact.json`,
  `tmp/peer-runner-live-transcript.txt`, this backlog receipt, and full gate
  output.
- Cadence: before any live Pi, Goose, OpenCode, OMP, or OpenRouter evaluation
  spend.

## Oracle

Cerberus can run:

```bash
CERBERUS_PEER_HARNESS_LIVE=1 cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- \
  --harness fixture-live \
  --profiles fixtures/harnesses/live-peer-command-profiles.json \
  --input fixtures/harnesses/peer-runner-input.json \
  --output tmp/peer-runner-live-artifact.json \
  --transcript-output tmp/peer-runner-live-transcript.txt

cargo run --locked -p cerberus-cli -- validate \
  tmp/peer-runner-live-artifact.json
```

and receive a completed `ReviewerArtifact.v1` parsed from the captured live
transcript.

At Backlog 016 close, default OpenRouter-backed peer profiles refused live
execution unless the operator set explicit provider-budget acknowledgement and
the profile avoided rendered-prompt argv transport. Backlog 017 later moves the
checked-in provider templates to private prompt-file transport.

## Scope

In scope:

- A reusable Rust bounded subprocess helper for command, args, optional stdin,
  timeout, process-group termination, and bounded transcript/diagnostic capture.
- Live peer runner execution for `argv_message`, `wrapper_rendered_prompt`, and
  `stdin_text` prompt modes.
- `--transcript-output <path>` for live transcript evidence.
- Explicit provider-budget acknowledgement for profiles that require paid
  provider execution.
- Refusal of provider-backed live profiles that would pass the rendered prompt
  and diff through argv.
- Fixture live peer profile and shell fixture.
- Docs, tests, QA commands, and retirement inventory updates.

Out of scope:

- Spending OpenRouter budget.
- Ranking harness/model quality.
- Retrying peer commands.
- Running peer tools outside the configured process group.
- Hosted API parity.

## Evidence

- Backlog 015 provides schema-valid execution plans.
- `cargo test -p cerberus-schema peer_harness`
- `cargo test -p cerberus-adapter bounded_command`
- `cargo test -p cerberus-adapter command_harness`
- `cargo test -p cerberus-cli peer_harness_live`
- `cargo test -p cerberus-cli peer_harness`
- `cargo run --locked -p cerberus-cli -- validate fixtures/harnesses/peer-command-profiles.json`
- `cargo run --locked -p cerberus-cli -- validate fixtures/harnesses/live-peer-command-profiles.json`
- `shellcheck fixtures/harnesses/live-peer-reviewer.sh`
- `CERBERUS_PEER_HARNESS_LIVE=1 cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- --harness fixture-live --profiles fixtures/harnesses/live-peer-command-profiles.json --input fixtures/harnesses/peer-runner-input.json --output tmp/peer-runner-live-artifact.json --transcript-output tmp/peer-runner-live-transcript.txt`
- `cargo run --locked -p cerberus-cli -- validate tmp/peer-runner-live-artifact.json`
- `test -s tmp/peer-runner-live-artifact.json`
- `test -s tmp/peer-runner-live-transcript.txt`
- `env -u CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK CERBERUS_PEER_HARNESS_LIVE=1 cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- --harness pi --input fixtures/harnesses/peer-runner-input.json --output tmp/peer-runner-budget-artifact.json --execution-plan-output tmp/peer-runner-budget-plan.json` returned non-zero before provider invocation.
- `cargo run --locked -p cerberus-cli -- validate tmp/peer-runner-budget-plan.json`
- `test ! -e tmp/peer-runner-budget-artifact.json`
- Regression coverage rejects blocked stdin writes that bypass timeout, invalid
  UTF-8 stdout transcripts, malformed live transcripts, provider profiles
  without budget acknowledgement, and provider profiles using argv prompt
  transport even when budget is acknowledged. Backlog 017 moves the checked-in
  provider profiles to private prompt-file transport.

## Result

`cerberus-peer-harness` now supports bounded live peer command invocation behind
`CERBERUS_PEER_HARNESS_LIVE=1`. It renders the review prompt, feeds it through
argv or stdin according to the profile, captures stdout as the transcript,
optionally writes `--transcript-output`, parses the marked artifact, and
validates the artifact against the request.

The bounded command primitive lives in `cerberus-adapter` and owns process
groups, timeout, descendant termination, side-threaded stdin, bounded strict
UTF-8 stdout capture, and bounded lossy stderr diagnostics. Provider-backed
profiles remain gated by `CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK=1`;
Backlog 017 adds private prompt-file transport before any provider-budget evals.

This slice still does not spend provider budget, rank harness/model quality,
or prove hosted/API review parity.
