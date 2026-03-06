# ADR 003: LLM-First Review Context Boundary via `github_read`

- Status: Accepted
- Date: 2026-03-03
- Deciders: Cerberus maintainers
- Related: #310, phrazzld/agent-skills#11

## Context

Reviewer quality depends on accurate semantic context:
- real acceptance criteria
- linked issue intent
- PR discussion decisions

We previously used deterministic workflow glue to inject acceptance criteria by parsing PR text and fetching a single linked issue body. That approach increased complexity and maintenance burden, and it was semantically weak (missed links, stale assumptions, brittle patterns).

This violates our LLM-first policy for semantic problems.

## Decision

We set a hard boundary:

1. Deterministic workflow bootstrap is narrow and syntactic only:
   - fetch PR diff
   - fetch lightweight PR metadata for prompt scaffolding
2. Semantic context retrieval is delegated to reviewer agents via read-only `github_read`:
   - PR details/comments
   - linked issues
   - issue search/read for backlog cross-checks
3. Remove deterministic acceptance-criteria injection and linked-issue regex inference from action glue.
4. Keep `github_read` as the deep module boundary:
   - small stable interface (`get_pr`, `get_pr_comments`, `get_linked_issues`, `get_issue`, `search_issues`)
   - implementation details (gh endpoints, GraphQL query form, filtering) hidden behind the tool.

## Consequences

### Positive

- Lower change amplification: one context module instead of multiple heuristic paths.
- Better semantic fidelity: agents fetch source-of-truth context directly.
- Cleaner trust boundary: workflow glue no longer decides semantic truth.
- Easier extension: backlog-aware and cross-issue review can evolve inside `github_read` without prompt rewrites.

### Negative / Tradeoffs

- Reviewer behavior now depends on tool usage quality and prompt discipline.
- Tool outages/auth issues can reduce review context quality unless fallback handling remains strong.

### Required Maintenance

- Keep `github_read` read-only and bounded.
- Keep contract tests on action set + payload shape.
- Keep prompt/skill instructions explicit that semantic context comes from the tool, not deterministic inference.

## Alternatives Considered

1. Deterministic AC extraction with improved regex/keyword rules.
   - Rejected: still heuristic semantics, still brittle, still high maintenance.
2. Keep both heuristic injection and `github_read`.
   - Rejected: duplicated sources of truth, shallow architecture, conflict risk.
3. Fully remove bootstrap metadata and fetch everything at runtime.
   - Deferred: possible later, but current split keeps startup deterministic and simple.
