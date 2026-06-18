# Cerberus Backlog

This backlog tracks the Rust resurrection work. Tickets are repo-owned planning
artifacts: each one should name the goal, oracle, verification system, scope,
and sequencing notes before implementation begins.

Current sequence:

1. `001-rust-review-engine-contract.md`
2. `002-independent-caller-adapters.md`
3. `003-thinktank-decommission-migration.md`
4. `004-daedalus-reviewer-config-promotion.md`
5. `005-legacy-surface-retirement.md`

Planning rules:

- Prefer one deep Rust engine surface over shallow wrappers around existing
  agents.
- Treat GitHub pull requests as the first adapter, not the core ontology.
- Keep Bitterblossom and Olympus independent sibling callers.
- Migrate useful ThinkTank review evidence into Cerberus before retiring it.
- Require fixture-backed or caller-backed proof before deleting legacy behavior.
