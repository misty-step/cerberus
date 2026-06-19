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
10. `010-peer-harness-command-profiles.md`
11. `011-peer-harness-protocol-runner.md`
12. `012-peer-harness-prompt-transcript.md`
13. `013-rust-local-review-replay.md`
14. `014-current-harness-model-catalog-refresh.md`
15. `015-peer-harness-execution-plan.md`
16. `016-peer-harness-live-invocation.md`
17. `017-peer-harness-prompt-file-transport.md`
18. `018-live-peer-harness-evaluation-mode.md`
19. `019-eval-report-reviewer-config-candidate.md`
20. `020-packet-backed-review-config.md`
21. `021-github-action-event-request-adapter.md`

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
- Record peer harness command profiles as validated data before implementing
  live protocol runners or spending model budget.
- Prove the peer harness file protocol offline before rendering prompts,
  parsing transcripts, or invoking paid providers.
- Parse only exact marked transcript artifacts; do not infer review findings
  from free-form harness prose.
- Prove local diff review through Rust fixtures before retiring the legacy
  Elixir local review command.
- Refresh current harness/model catalog facts as dated evidence before spending
  live eval budget or promoting reviewer defaults.
- Write an inspectable execution plan before live peer harness invocation,
  provider spend, or harness/model promotion.
- Prove live peer command invocation with a fixture profile, then private
  prompt-file transport, before budget-approved provider evals or default
  reviewer promotion.
- Run at least one local live peer eval cell and capture its evidence packet
  before spending provider eval budget or promoting defaults.
- Convert passing live eval reports into sandbox-only reviewer config packets
  before any reviewer defaults or Daedalus promotion packets are hand-authored.
- Let Rust review commands consume validated reviewer config packets directly
  before caller integrations depend on measured configs.
- Move GitHub Action event preflight and request construction into a Rust
  adapter before replacing shell POST/poll behavior.
