# Backlog Priorities

## Primary Goal

Resurrect Cerberus as the Rust review engine and artifact contract for
source-agnostic code review.

## Current Themes

- Rust contract spine: request/config/reviewer-artifact/run-artifact schemas.
- Review execution parity: routing, reviewer orchestration, aggregation,
  finding dedupe, cost, coverage, and degradation.
- Independent caller adapters: Bitterblossom and Olympus call Cerberus through
  the same contract, never through each other.
- ThinkTank migration: absorb useful review-bench artifacts and retire the
  separate review-engine role.
- Harness/model evaluation: compare Pi, Goose, OpenCode, OMP, and current
  coding models with Cerberus-owned reviewer fixtures before changing defaults.
- Daedalus promotion loop: import only measured reviewer configurations.
- Legacy retirement: keep the current GitHub action/API as compatibility until
  Rust proves parity, then delete or archive stale Elixir surfaces.

## Active Migration Spine

- `backlog.d/001-rust-review-engine-contract.md`
- `backlog.d/006-harness-model-evaluation.md`
- `backlog.d/002-independent-caller-adapters.md`
- `backlog.d/003-thinktank-decommission-migration.md`
- `backlog.d/004-daedalus-reviewer-config-promotion.md`
- `backlog.d/005-legacy-surface-retirement.md`

## Planning Rule

Prefer work that:

1. makes the contract smaller and more stable
2. moves durable engine behavior into Rust
3. proves review quality with artifact fixtures or caller integration tests
4. promotes harnesses and models from dated eval evidence, not model hype
5. preserves Bitterblossom/Olympus independence
6. deletes duplicate orchestration after parity is proven
