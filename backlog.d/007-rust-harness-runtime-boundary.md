# 007 - Rust Harness Runtime Boundary

Status: implemented-boundary
Priority: P0
Type: epic
Created: 2026-06-18

## Goal

Move Cerberus core review execution behind a Rust-owned harness runtime
boundary.

The core should aggregate reviewer artifacts from a narrow executor interface
instead of calling fixture-only fake review logic directly. That boundary is the
step that lets Pi, Goose, OpenCode, OMP, Sprites, local CLIs, and hosted
providers plug in without becoming core semantics.

## Oracle

`cerberus-core` exposes a small review execution interface that:

- receives validated `ReviewRequest.v1` and `ReviewerConfig` values
- returns schema-valid `ReviewerArtifact.v1` values per reviewer
- preserves current fake/offline behavior through a deterministic default
  runner
- records degraded reviewer failures as artifacts instead of panicking
- keeps aggregation, dedupe, cost, coverage, overrides, reserves, and rendering
  unchanged

## Verification System

- `cargo test --workspace harness_runtime`
- `cargo test --workspace`
- Existing CLI fixture review still emits the same checked artifact shape.
- Legacy gates continue to pass until runtime parity is strong enough for
  deletion.

## Scope

In scope:

- Rust `ReviewHarness` or equivalent execution boundary.
- Default deterministic harness implementation for current fixtures.
- Tests proving custom harness artifacts feed aggregation.
- Tests proving runner errors become degraded reviewer artifacts.
- Docs that explain how future harness adapters attach.

Out of scope:

- Running live Pi/Goose/OpenCode/OMP commands.
- Network provider clients.
- Replacing `dispatch.sh` or the hosted API.
- Deleting Elixir execution modules.

## Evidence

- Backlog 005 inventory marks Elixir review execution pending until Rust can
  own routing, degraded reviewers, and local-review fixtures.
- Current `cerberus-core::review` calls fixture fake review logic directly,
  which blocks arbitrary harness injection.
- Harness/model evaluation already separates harness identity from model
  scoring, but review execution still needs the same boundary.

## Implementation Receipt

First local runtime-boundary delivery, 2026-06-18:

- Added `ReviewHarness`, `HarnessRuntimeError`, and `DeterministicHarness`.
- Routed `review` through `review_with_harness` while preserving current
  deterministic fixture behavior.
- Added boundary checks that reject mismatched/invalid harness artifacts by
  recording degraded reviewer artifacts, including reviewer identity, finding
  identity, finding citation coverage, and verdict/finding consistency.
- Added focused tests for custom harness aggregation, runner failure
  degradation, and artifact identity mismatch degradation.
- Documented the boundary in
  `docs/shaping/rust-harness-runtime-boundary.md`.
