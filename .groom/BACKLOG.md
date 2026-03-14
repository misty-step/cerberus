# Cerberus Backlog (Icebox)

Ideas, deferred work, and research prompts not in the active GitHub backlog.
Reviewed each /groom session for promotion candidates.

## High Potential

### Auto-skip bot and WIP PRs
Formerly #258. Skip dependabot/renovate/github-actions[bot] PRs and WIP title patterns in preflight. Implement in Elixir router/preflight logic post-migration.

### Incremental review awareness
Formerly #291. Skip/narrow re-reviews for small delta commits. Delta-based depth, scope narrowing, "sanity check" mode. Requires stable routing layer first. XL effort.

### AC compliance in verdict rendering
Formerly #312 partially. Parse AC compliance findings, render as checklist in PR comment. Depends on migration + #311 trace enhancement.

### AC-aware escalation
Formerly #313. If any AC is NOT_SATISFIED by primary panel, trigger reserve reviewers with unsatisfied ACs as context. Replaces wave gating with smarter reserve trigger.

## Someday / Maybe

### Adversarial testing ("Angry Mob" pattern)
Formerly #21. Concurrent adversarial attack patterns against the review system. Race conditions in verdict aggregation, comment parsing under concurrent overrides, resource exhaustion. P3 research.

### Auto-detect consumer package manager
Formerly #261. Auto-detect and set up correct tool (bun, pnpm, yarn, npm) in GHA action. May not be relevant if execution moves to Fly.io.

### Cross-model confirmation
Wave3 ran the same perspectives as wave1 with pro-tier models. In single-pass mode, consider an optional "confirmation" mode where a second model reviews high-severity findings.

### Parallel permission lookups for overrides
Formerly #126. Sequential gh API calls per actor. Trivial to parallelize in Elixir with Task.async.

## Research Prompts

- What's the optimal panel size? Is 4 reviewers the right default or should it vary by PR complexity?
- Should reserve reviewers see primary panel findings, or review independently?
- How does model diversity (different providers) compare to model homogeneity for finding quality?
- SWR-Bench shows +43.67% F1 from multi-review aggregation — what's the diminishing returns curve?
- Can we use a cheap model to pre-filter/summarize diffs before sending to perspective reviewers (CodeRabbit pattern)?

## Archived This Session (2026-03-14)

- ~~#256 Remove phantom perspectives~~ -> subsumed by migration
- ~~#257 Extract magic numbers~~ -> Python eliminated
- ~~#260 Rename consumer-workflow-minimal~~ -> new workflow surface
- ~~#264 craft parse recovery fails~~ -> parser rewritten
- ~~#266 Skip diagnostics edge case~~ -> renderer rewritten
- ~~#267 Consolidate skip classification~~ -> renderer rewritten
- ~~#283 minimax-m2.5 fails JSON~~ -> model pool redesign
- ~~#284 Comment cleanup/positioning~~ -> GH integration rewritten
- ~~#287 Extract runtime state machine~~ -> GenServer
- ~~#288 Clarify capability policy~~ -> config module
- ~~#320 Fix set -e bypass~~ -> bash eliminated
- ~~#322 Expose draft/path skips~~ -> new preflight
- ~~#327 Unify consumer contract~~ -> new contract
- ~~#354 Refactor finding equivalence~~ -> rewritten in Elixir
- ~~#366 Align make validate~~ -> Python tooling eliminated
- ~~#239 Tighten validator test~~ -> new workflow surface
- ~~#57 Read-only context broker~~ -> Elixir tool definitions
- ~~#323 Extract engine from GHA~~ -> IS the migration
- ~~#343 Bench-aware router~~ -> new router design
- ~~#344 Configurable benches epic~~ -> persona registry
- ~~#345 Repo-defined bench manifests~~ -> per-repo config
- ~~#321 Seed router with priors~~ -> new router design
- ~~#346 Replace wave orchestration~~ -> core migration goal
- ~~#313 AC-aware wave gating~~ -> waves eliminated
- ~~#126 Parallel permission lookups~~ -> trivial in Elixir
