# Cerberus Backlog

This backlog tracks the Rust resurrection work. Tickets are repo-owned planning
artifacts: each one should name the goal, oracle, verification system, scope,
and sequencing notes before implementation begins.

Current sequence:

1. `001-rust-review-engine-contract.md`
2. `006-harness-model-evaluation.md`
3. `002-independent-caller-adapters.md`
4. `003-thinktank-decommission-migration.md`
5. `004-daedalus-reviewer-config-promotion.md`
6. `005-legacy-surface-retirement.md`
7. `007-rust-harness-runtime-boundary.md`
8. `008-current-model-catalog-ingestion.md`
9. `009-rust-command-harness-adapter.md`

Planning rules:

- Prefer one deep Rust engine surface over shallow wrappers around existing
  agents.
- Treat GitHub pull requests as the first adapter, not the core ontology.
- Keep Bitterblossom and Olympus independent sibling callers.
- Migrate useful ThinkTank review evidence into Cerberus before retiring it.
- Evaluate harness/model pairs with Cerberus-owned fixtures before changing
  reviewer defaults.
- Require fixture-backed or caller-backed proof before deleting legacy behavior.
- Route reviewer execution through the Rust harness boundary before wiring live
  provider or peer-harness commands.
- Refresh model catalog facts from cached raw evidence before promoting or
  comparing harness/model candidates.
- Keep subprocess harness launchers in adapter crates; `cerberus-core` owns
  artifact acceptance and aggregation, not shell execution.
