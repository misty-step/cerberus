# 017 - Peer Harness Prompt File Transport

Status: implemented-local
Priority: P0
Type: feature
Created: 2026-06-19

## Goal

Move provider-backed peer harness profiles off rendered-prompt argv transport.
Backlog 016 proved fixture-backed live invocation and correctly blocked
provider profiles that would leak the diff through process arguments. This
slice adds a private prompt-file handoff so later budget-approved provider evals
can run without exposing review context in argv.

## Verification System

- Claim: Cerberus can render a peer review prompt to a private temporary file,
  pass only that file path to the peer harness, capture the live transcript,
  and delete the prompt file after execution.
- Falsifier: a provider execution plan includes rendered diff text in argv,
  a provider profile is still blocked for argv prompt transport, a prompt file
  is not private, a prompt temp file persists after execution, or fixture live
  prompt-file mode cannot produce a valid artifact.
- Driver: `CERBERUS_PEER_HARNESS_LIVE=1 cerberus-peer-harness --harness
  fixture-live-file --profiles fixtures/harnesses/live-peer-command-profiles.json`.
- Grader: focused schema/CLI tests, live fixture artifact validation,
  transcript-output contents, provider execution-plan inspection, and no leaked
  prompt temp path after the run.
- Evidence packet: `tmp/peer-runner-file-artifact.json`,
  `tmp/peer-runner-file-transcript.txt`, provider plan tmp files, and this
  backlog receipt.
- Cadence: before any budget-approved Pi, Goose, OpenCode, OMP, or OpenRouter
  evaluation spend.

## Oracle

Cerberus can run:

```bash
CERBERUS_PEER_HARNESS_LIVE=1 cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- \
  --harness fixture-live-file \
  --profiles fixtures/harnesses/live-peer-command-profiles.json \
  --input fixtures/harnesses/peer-runner-input.json \
  --output tmp/peer-runner-file-artifact.json \
  --transcript-output tmp/peer-runner-file-transcript.txt

cargo run --locked -p cerberus-cli -- validate \
  tmp/peer-runner-file-artifact.json
```

and receive a completed `ReviewerArtifact.v1` parsed from a live transcript.
The fixture must read the prompt from the path passed in argv, not from argv
prompt text or stdin.

Provider profiles must validate with a prompt-file transport mode and live
execution with budget acknowledgement must not fail because of argv prompt
transport. It may still fail closed on missing provider credentials.

## Scope

In scope:

- `PeerHarnessPromptMode::PromptFile` or equivalent schema support.
- Private prompt-file creation, cleanup, and permission checks in the Rust
  peer runner.
- Prompt-file fixture mode and profile.
- Pi, Goose, OpenCode, and OMP profile templates updated to path-based prompt
  handoff according to locally observed CLI help.
- Execution-plan text that keeps `{prompt_file}` as a placeholder and never
  embeds rendered prompt text.
- Tests, docs, QA commands, and retirement inventory updates.

Out of scope:

- Spending provider budget.
- Scoring model or harness quality.
- Retrying peer commands.
- Hosted API parity.
- General file-upload abstractions beyond the peer prompt file.

## Evidence

- `cargo test -p cerberus-schema peer_harness`
- `cargo test -p cerberus-cli peer_harness_live`
- `cargo run --locked -p cerberus-cli -- validate fixtures/harnesses/peer-command-profiles.json fixtures/harnesses/live-peer-command-profiles.json docs/shaping/legacy-surface-retirement.json`
- `shellcheck fixtures/harnesses/live-peer-reviewer.sh`
- `CERBERUS_PEER_HARNESS_LIVE=1 cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- --harness fixture-live-file --profiles fixtures/harnesses/live-peer-command-profiles.json --input fixtures/harnesses/peer-runner-input.json --output tmp/peer-runner-file-artifact.json --transcript-output tmp/peer-runner-file-transcript.txt`
- `cargo run --locked -p cerberus-cli -- validate tmp/peer-runner-file-artifact.json`
- `test -s tmp/peer-runner-file-artifact.json`
- `test -s tmp/peer-runner-file-transcript.txt`
- `rg -n "PROMPT_FILE=|PROMPT_FILE_MODE=600|CERBERUS_REVIEWER_ARTIFACT_JSON_BEGIN|CERBERUS_REVIEWER_ARTIFACT_JSON_END|\"verdict\"|\"status\"" tmp/peer-runner-file-transcript.txt tmp/peer-runner-file-artifact.json`
- `prompt_path=$(sed -n 's/^PROMPT_FILE=//p' tmp/peer-runner-file-transcript.txt); test -n "$prompt_path"; test ! -e "$prompt_path"`
- `env -u CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK CERBERUS_PEER_HARNESS_LIVE=1 cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- --harness pi --input fixtures/harnesses/peer-runner-input.json --output tmp/peer-runner-budget-artifact.json --execution-plan-output tmp/peer-runner-budget-plan.json` returned non-zero before provider invocation.
- `cargo run --locked -p cerberus-cli -- validate tmp/peer-runner-budget-plan.json`
- `test ! -e tmp/peer-runner-budget-artifact.json`
- `env -u OPENROUTER_API_KEY CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK=1 CERBERUS_PEER_HARNESS_LIVE=1 cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- --harness pi --input fixtures/harnesses/peer-runner-input.json --output tmp/peer-runner-budget-ack-artifact.json --execution-plan-output tmp/peer-runner-budget-ack-plan.json` returned non-zero at the missing `OPENROUTER_API_KEY` gate.
- `cargo run --locked -p cerberus-cli -- validate tmp/peer-runner-budget-ack-plan.json`
- `test ! -e tmp/peer-runner-budget-ack-artifact.json`
- `cargo test --workspace`
- `cargo fmt --all -- --check`
- `git diff --check`
- `shellcheck dispatch.sh fixtures/harnesses/command-reviewer.sh fixtures/harnesses/live-peer-reviewer.sh`
- `node --check bin/cerberus.js`
- `cargo run --locked -p cerberus-cli -- validate-retirement docs/shaping/legacy-surface-retirement.json`
- `cd cerberus-elixir && mix test`
- `cd cerberus-elixir && mix format --check-formatted`

## Result

`PeerHarnessPromptMode::PromptFile` is now schema-validated for command
profiles and execution plans. Provider profiles may not contain `{prompt}` in
prompt-file mode, and must contain exactly one `{prompt_file}` placeholder.

`cerberus-peer-harness` now writes rendered prompts for prompt-file profiles to
a private temporary file, substitutes only the path into peer args, runs the
bounded peer command, and removes the prompt file when execution finishes. The
local `fixture-live-file` profile proves the path-based handoff with file mode
`600`, a completed live artifact, captured transcript, and post-run cleanup.

Pi, Goose, OpenCode, and OMP checked-in provider profiles now use prompt-file
handoff grounded in local CLI help. They remain gated by explicit provider
budget acknowledgement and required environment variables. This slice does not
spend provider budget, rank harness/model quality, or promote reviewer
defaults.
