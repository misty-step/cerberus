# 026 - Archive Shell Dispatcher

Status: planned
Priority: P0
Type: compatibility
Created: 2026-06-19

## Goal

Delete the retired root `dispatch.sh` shell dispatcher after backlog 025 moved
the public composite action to `cerberus-cli github-action-dispatch`.

The action should keep the same public input/output contract, but the repository
should no longer ship a rollback implementation that can drift from the Rust
dispatcher.

## Verification System

- Claim: the root action remains Rust-backed and `dispatch.sh` is archived with
  a recorded deletion commit in the retirement inventory.
- Falsifier: `dispatch.sh` still exists, the composite action invokes a shell
  dispatcher, retirement validation cannot pass after the archive, local action
  dispatch no longer writes `review-id` and `verdict`, or docs still describe
  the shell dispatcher as the current client.
- Driver:
  - `cargo test -p cerberus-cli --test github_action_entrypoint`
  - `cargo test -p cerberus-cli retirement_path_validation`
  - `cargo test -p cerberus-cli --test github_action_dispatch`
  - local QA command that builds with hosted secrets unset, then runs
    `"$CARGO_TARGET_DIR/debug/cerberus-cli" github-action-dispatch`
- Grader: repo test for absence of `dispatch.sh`, action YAML contract
  assertions, retirement validator over the archive receipt, and fake hosted API
  assertions over request, outputs, decision JSON, verdict JSON, and exit
  status.
- Evidence packet: `tmp/archive-shell-dispatcher-2026-06-19/`.
- Cadence: before changing action outputs, release rollback policy, or consumer
  templates.

## Scope

In scope:

- Delete `dispatch.sh`.
- Keep `action.yml` inputs, outputs, and Rust invocation stable.
- Teach retirement validation that missing archived paths are valid only when a
  deletion/archive commit is recorded.
- Update README, architecture, API contract, AGENTS, backlog sequence, docs
  index, and retirement inventory.
- Record the archive commit after the deletion commit lands.

Out of scope:

- Changing action input names or output names.
- Publishing prebuilt action binaries.
- Porting the hosted API from Elixir.
- Removing historical walkthroughs or completed backlog tickets that mention
  `dispatch.sh` as past state.

## Evidence

- Plan: `docs/shaping/026-archive-shell-dispatcher-plan.html`
- Focused tests:
  - `cargo test -p cerberus-cli --test github_action_entrypoint`
  - `cargo test -p cerberus-cli retirement_path_validation`
  - `cargo test -p cerberus-cli --test github_action_dispatch`
- QA packet:
  `tmp/archive-shell-dispatcher-2026-06-19/`
- Action-shaped command:
  `tmp/archive-shell-dispatcher-2026-06-19/action-shaped-dispatch.log`

## Result

Planned. The deletion commit must land first, then the retirement inventory must
record that commit hash in a follow-up receipt commit.
