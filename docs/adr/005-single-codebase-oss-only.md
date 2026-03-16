# ADR 005: Single Codebase, OSS-Only

- Status: Accepted
- Date: 2026-03-15
- Deciders: Cerberus maintainers
- Supersedes: ADR 002 (OSS Core + Cerberus Cloud split)

## Context

ADR 002 established a two-product model: an OSS GitHub Action (this repo) plus a separate Cerberus Cloud managed service (GitHub App + Marketplace billing).

The Elixir migration (epic #385) eliminated the pipeline separation that justified a separate cloud product. The BEAM process model handles orchestration, concurrency, and state management natively — the capabilities that cerberus-cloud was built to provide on top of the Python/Shell pipeline.

Building and maintaining a managed service, billing system, and marketing site divides focus from the core problem: making the best possible AI code review tool.

## Decision

1. **Single codebase.** All Cerberus development happens in this repository.
2. **OSS-only distribution.** GitHub Action with BYOK model key. No managed service, no GitHub App, no billing.
3. **Archive cerberus-cloud and cerberus-web.** Moved to `_archived/` in the monorepo root. Historical ADRs preserved in-place.
4. **Monetization deferred.** Focus on building the best OSS tool first. Revenue model revisited when the product has clear pull.

## Consequences

Positive:
- One codebase to maintain, test, and reason about.
- No billing/quota/org-controls complexity.
- All engineering effort concentrated on review quality.
- Elixir migration proceeds without dual-mode concerns.

Negative:
- No revenue path in the short term.
- Users who wanted zero-config managed onboarding must self-host.

## Alternatives Considered

- Port billing to Elixir and maintain Cloud: rejected (premature; divides focus before product-market fit).
- Keep cerberus-cloud alive as a thin wrapper: rejected (maintenance cost with no users).
