# 009 - Rust Command Harness Adapter

Status: done
Priority: P0
Type: epic
Created: 2026-06-18

## Goal

Add a Rust-owned command adapter for external reviewer harnesses without putting
shell execution in `cerberus-core`.

Backlog 007 introduced the `ReviewHarness` boundary. This slice gives that
boundary a real subprocess adapter that can later wrap Pi, Goose, OpenCode,
OMP, Sprites launchers, or local provider scripts. The adapter must be usable in
tests without paid model calls.

## Oracle

`cerberus-adapter` exposes a command harness adapter that:

- implements `cerberus_core::ReviewHarness`
- writes a reviewer/request input envelope for each reviewer
- launches a configured command with explicit `--input` and `--output` paths
- parses `ReviewerArtifact.v1` from the output path
- returns timeout and non-zero command exits as `HarnessRuntimeError`
- leaves core aggregation, validation, and degradation behavior in
  `cerberus-core`

## Verification System

- `cargo test --workspace command_harness`
- fixture command success feeds `review_with_harness` and produces a valid
  `ReviewRunArtifact.v1`
- fixture command non-zero exit degrades the reviewer
- fixture command timeout degrades the reviewer as timeout
- full repo gates continue to pass

## Scope

In scope:

- `cerberus-adapter` command harness implementation.
- Deterministic fixture command used by tests.
- Docs for the command protocol.

Out of scope:

- Paid Pi/Goose/OpenCode/OMP model calls.
- Prompt construction for each peer harness.
- Provider credentials.
- Hosted API replacement.

## Evidence

- Backlog 007 documents `ReviewHarness` but leaves live command execution out
  of core.
- Legacy retirement inventory still marks Elixir review execution pending until
  Rust can own routing, timeout, degraded reviewers, and local-review fixtures.

## Implementation Receipt

First local delivery, 2026-06-18:

- Added `CommandHarness` and `CommandHarnessInput` in `cerberus-adapter`.
- Added the command protocol: configured args plus `--input <json>` and
  `--output <json>`.
- Captured stdout/stderr to temp files and converted non-zero exits and
  timeouts into `HarnessRuntimeError`.
- Added `fixtures/harnesses/command-reviewer.sh` for success, non-zero, and
  timeout tests without paid model calls.
- Proved all paths through `cerberus_core::review_with_harness`.
- Hardened temp handling with private run directories, cleanup on return, Unix
  process-group timeout termination, bounded stderr diagnostics, and fixture
  checks for reviewer id, request id, head SHA, diff body, and changed path.
- Residual boundary: command adapters are not sandboxes. Daemonizing commands
  and unbounded live output file growth remain follow-up containment work.
