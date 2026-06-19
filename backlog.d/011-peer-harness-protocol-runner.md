# 011 - Peer Harness Protocol Runner

Status: done
Priority: P0
Type: epic
Created: 2026-06-18

## Goal

Implement the Rust `cerberus-peer-harness` protocol runner that the
`PeerHarnessCommandProfiles.v3` fixture points at.

This runner proves the `CommandHarness` file protocol for Pi, Goose, OpenCode,
and OMP without making live model calls. It validates the selected profile,
reads `CommandHarnessInput`, and emits a schema-valid `ReviewerArtifact.v1`
with exact request coverage.

## Oracle

Cerberus can run:

```bash
cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- \
  --harness pi \
  --input <CommandHarnessInput.json> \
  --output <ReviewerArtifact.v1.json>
```

and receive a valid reviewer artifact that:

- uses the configured reviewer id, perspective, and model from the input
- covers every request file and no extra file
- reports `status: degraded` and `verdict: SKIP` in offline mode
- records a clear degraded reason explaining that live peer execution is not
  implemented in this slice
- refuses live peer/provider execution until a transcript/parser oracle exists

## Verification System

- `cargo test --workspace peer_harness_runner`
- `cargo test -p cerberus-cli --test peer_harness_command`
- focused runner invocation through the Rust test fixture
- `cargo run --locked -p cerberus-cli -- validate <emitted ReviewerArtifact.v1>`
- full repo gates continue to pass

## Scope

In scope:

- Rust binary target for `cerberus-peer-harness`.
- Argument parsing for `--harness`, `--input`, `--output`, and optional
  `--profiles`.
- Profile packet validation and selected harness lookup.
- Offline `ReviewerArtifact.v1` emission.
- Tests for success, unknown harness, missing input/output args, and fail-closed
  live mode.
- Docs that state what is and is not proven.

Out of scope:

- Invoking Pi, Goose, OpenCode, or OMP.
- Rendering final review prompts.
- Parsing peer harness JSON or transcripts.
- Spending OpenRouter or provider budget.
- Ranking harness/model quality.

## Evidence

- Backlog 009 provides `CommandHarness` and process/file containment.
- Backlog 010 provides validated peer harness command profiles.
- `crates/cerberus-core` already validates harness artifacts for reviewer
  identity, model, and exact request coverage.

## Implementation Receipt

First local delivery, 2026-06-18:

- Added the Rust `cerberus-peer-harness` binary to the `cerberus-cli` package
  while preserving `cerberus-cli` as the default `cargo run` target.
- Added offline runner logic that validates profile packets, selects a harness
  profile, reads `CommandHarnessInput`, and writes a degraded `SKIP`
  `ReviewerArtifact.v1` with exact request coverage.
- Added an integration test that launches the real `cerberus-peer-harness`
  binary through `CommandHarness`.
- Added a fail-closed live-mode guard for `CERBERUS_PEER_HARNESS_LIVE=1`.
- Added a focused input fixture at `fixtures/harnesses/peer-runner-input.json`.
- Documented the offline protocol boundary and updated architecture,
  runtime-boundary, profile, backlog, and retirement inventory docs.
- Verified with:
  - `cargo test --workspace peer_harness_runner`
  - `cargo test -p cerberus-cli --test peer_harness_command`
  - `cargo run --locked -p cerberus-cli -- validate fixtures/harnesses/peer-command-profiles.json`
  - `cargo run --locked -p cerberus-cli -- validate-retirement docs/shaping/legacy-surface-retirement.json`
  - `cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- --harness pi --input fixtures/harnesses/peer-runner-input.json --output tmp/peer-runner-artifact.json`
  - `cargo run --locked -p cerberus-cli -- validate tmp/peer-runner-artifact.json`
  - `cargo test --workspace`
  - `cargo fmt --all -- --check`
  - `git diff --check`
  - `shellcheck dispatch.sh fixtures/harnesses/command-reviewer.sh`
  - `node --check bin/cerberus.js`
  - `cd cerberus-elixir && mix format --check-formatted`
  - `cd cerberus-elixir && mix test`
