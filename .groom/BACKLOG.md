# Cerberus Backlog (Icebox)

Ideas, deferred work, and research prompts not in the active GitHub backlog.
Reviewed each /groom session for promotion candidates.

## High Potential

### Triage port to Elixir
Formerly `scripts/triage.py` (505 LOC). Post-verdict diagnosis, circuit breaker, optional fix command. Currently Python-only — defer until after Python decommission, then port or redesign as an Elixir pipeline stage. XL effort.

### Auto-skip bot and WIP PRs
Formerly #258. Skip dependabot/renovate/github-actions[bot] PRs and WIP title patterns. Implement in Elixir API preflight logic. S effort.

### Incremental review awareness
Formerly #291. Skip/narrow re-reviews for small delta commits. Delta-based depth, scope narrowing, "sanity check" mode. Requires stable Engine module first. XL effort.

### AC-aware escalation
Formerly #313. If any AC is NOT_SATISFIED by primary panel, trigger reserve reviewers with unsatisfied ACs as context. Replaces wave gating with smarter reserve trigger. M effort.

## Quality Phase (Post-Migration)

### Eval suite hardening
Port and expand the 31 promptfoo eval test cases. Add SWR-Bench and CR-Bench integration. Measure recall/precision per perspective. Target: >= 85% recall on gold-standard set.

### Prompt engineering audit
Use /context-engineering to audit all persona prompts (pi/agents/*.md) for signal density, instruction clarity, and grounding. Optimize token budget per perspective.

### Observability dashboard
Phoenix LiveView dashboard for review runs, costs, latency, model performance. Already scaffolded (#394 closed) but needs real data + deployment.

### Review transparency
Structured trace of review execution: which tools were called, what the reviewer saw, how confidence was computed. Surface in PR comment or dashboard.

### Consumer workflow validator (Elixir)
Port `validate-consumer-workflow.py` to a mix task or API endpoint. Low priority — only useful for onboarding new repos.

## Someday / Maybe

### Adversarial testing ("Angry Mob" pattern)
Formerly #21. Concurrent adversarial attack patterns against the review system. Race conditions in verdict aggregation, resource exhaustion. P3 research.

### Cross-model confirmation
Optional "confirmation" mode where a second model reviews high-severity findings. Could be a reserve trigger variant.

### Parallel permission lookups for overrides
Formerly #126. Trivial in Elixir with Task.async — already natural in the current architecture.

## Research Prompts

- What's the optimal panel size? Is 4 reviewers the right default or should it vary by PR complexity?
- Should reserve reviewers see primary panel findings, or review independently?
- How does model diversity (different providers) compare to model homogeneity for finding quality?
- SWR-Bench shows +43.67% F1 from multi-review aggregation — what's the diminishing returns curve?
- Can we use a cheap model to pre-filter/summarize diffs before sending to perspective reviewers (CodeRabbit pattern)?
- What's the right local-run experience? Should `mix cerberus.review` support reviewing uncommitted changes (git diff)?
- How should the CLI handle GitHub tool calls when running locally (mock, skip, or require token)?

## Archived This Session (2026-03-22)

- ~~AC compliance in verdict rendering~~ → #312 retargeted to Elixir engine (ac_compliance not yet in Elixir)
- ~~Auto-detect consumer package manager~~ → irrelevant post-GHA-decommission
