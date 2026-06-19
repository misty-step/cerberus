# 025 - Rust Action Entrypoint

Status: implemented
Priority: P0
Type: compatibility
Created: 2026-06-19

## Goal

Wire the public composite action to the Rust hosted API dispatcher from backlog
024. The root action should keep the same inputs and outputs for consumers, but
its dispatch step should invoke `cerberus-cli github-action-dispatch` through
Cargo instead of running `dispatch.sh`.

`dispatch.sh` stays in the repository as a rollback surface until the Rust
entrypoint has fixture-backed parity and a later deletion slice can remove it
without weakening compatibility.

## Verification System

- Claim: `action.yml` now runs the Rust dispatcher while preserving the
  consumer workflow contract for env wiring, fork/draft skips, hosted API
  polling, `review-id`, `verdict`, fail-on-verdict, and verdict JSON output.
- Falsifier: the composite action still invokes `dispatch.sh`, omits a required
  env mapping, interpolates the action path only inside the run body, passes
  hosted secrets into Cargo builds, writes different output names, requires
  hosted secrets for fork or draft skips, or the action-shaped build-plus-run
  command cannot run the dispatcher against a local fake API.
- Driver:
  - `cargo test -p cerberus-cli --test github_action_entrypoint`
  - `cargo test -p cerberus-cli --test github_action_dispatch`
  - local QA command that builds with `CERBERUS_API_KEY` and `GITHUB_TOKEN`
    unset, then runs
    `"$CARGO_TARGET_DIR/debug/cerberus-cli" github-action-dispatch`
- Grader: exact action file assertions plus fake hosted API assertions over
  request method, path, auth, payload, output-file contents, decision JSON,
  verdict JSON, and process status.
- Evidence packet: `tmp/rust-action-entrypoint-2026-06-19/`.
- Cadence: before deleting `dispatch.sh` or changing the public action outputs.

## Scope

In scope:

- Change `action.yml` dispatch step to invoke the Rust command.
- Keep consumer inputs and outputs stable.
- Add fixture-backed tests for action YAML wiring.
- Update retirement inventory, architecture docs, README, and backlog sequence.
- Run local QA through the action-shaped Cargo invocation.

Out of scope:

- Deleting `dispatch.sh`.
- Publishing prebuilt binaries.
- Changing action input names or output names.
- Live hosted Cerberus credentials.
- Porting the hosted API server from Elixir.

## Evidence

- Plan: `docs/shaping/025-rust-action-entrypoint-plan.html`
- Focused tests:
  - `cargo test -p cerberus-cli --test github_action_entrypoint`
  - `cargo test -p cerberus-cli --test github_action_dispatch`
- QA packet:
  `tmp/rust-action-entrypoint-2026-06-19/`
- Action-shaped command:
  `tmp/rust-action-entrypoint-2026-06-19/action-shaped-dispatch.log`

## Result

Implemented. The root composite action now builds `cerberus-cli` through Cargo
from the checked-out action workspace with hosted secrets scrubbed from the
build environment, then invokes `cerberus-cli github-action-dispatch` with the
runtime env. Build output is directed to `RUNNER_TEMP`. The public inputs and
outputs remain stable. `dispatch.sh` remains in the repo only as rollback until
a later deletion slice records its archive commit.
