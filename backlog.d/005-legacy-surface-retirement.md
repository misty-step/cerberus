# 005 - Legacy Surface Retirement

Status: shaped
Priority: P2
Type: epic
Created: 2026-06-18

## Goal

Retire or archive legacy Cerberus surfaces after the Rust engine proves parity
for the paths they currently support.

The objective is not a rewrite for its own sake. The objective is a smaller
repo whose public surface is Rust engine + adapter contracts, with legacy Elixir
and GitHub-only assumptions preserved only where they still buy compatibility.

## Oracle

For each legacy surface, a retirement table records:

- current responsibility
- Rust replacement or explicit reason to keep it
- parity fixture or caller test
- deletion/archive commit
- rollback path

No legacy engine module is deleted until its behavior is covered by Rust
fixtures or intentionally rejected as out of scope.

## Verification System

- Retirement table checked into `docs/shaping/`.
- `cargo test --workspace` covers replacement behavior.
- Legacy gates keep passing until the relevant surface is removed.
- Final retirement PR leaves `git status --short --untracked-files=all` clean
  and docs with no stale "Elixir engine is current" claims.

## Scope

In scope:

- `cerberus-elixir/` parity inventory.
- Root action/API compatibility decision.
- Node scaffolder compatibility decision.
- Old walkthrough/artifact cleanup or archive tags.
- AGENTS/docs source-of-truth updates as surfaces retire.

Out of scope:

- Deleting working compatibility before caller migration.
- Renaming public action refs without a migration plan.
- Keeping duplicate Elixir and Rust engines indefinitely.

## Evidence

- The repo already decommissioned the prior Python/Shell matrix pipeline.
- The current docs still name the Elixir engine as active, which will become
  stale as soon as Rust work lands.
- ADR 004 and the new backlog both point toward contracts as the durable seam.

## Child Work

1. Create the legacy responsibility inventory.
2. Mark each surface keep/port/delete/archive.
3. Add parity fixtures for kept behavior.
4. Delete or archive retired surfaces in small commits after parity.
5. Update README, docs, AGENTS, and templates after each retirement.

## Notes

This is intentionally sequenced after backlog 001 and 002. Premature deletion
would erase useful donor behavior before the Rust engine can prove it.
