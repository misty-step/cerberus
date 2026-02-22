# ADR 002: OSS Core + Cerberus Cloud (GitHub App) Split

- Status: Accepted
- Date: 2026-02-16
- Deciders: Cerberus maintainers
- Related: vision.md, docs/ARCHITECTURE.md, #145

## Context

Cerberus today is an open source GitHub Action that runs a multi-perspective PR review (BYO model key).

We want a path to a profitable, managed product (Cerberus Cloud) without turning the OSS action into a SaaS-shaped monolith.

Constraints:
- Keep the OSS core useful for our own autonomous dev workflows.
- Keep installs low-friction and safe (least-privilege, untrusted PR boundaries).
- Avoid dashboard sprawl; prefer GitHub-native UX (checks, comments, PR reviews).
- Preserve Unix composability: focused modules with clean interfaces.

## Decision

1. **This repo remains the OSS core**:
   - GitHub Action(s) for review + verdict + triage.
   - BYO key model (OpenRouter, etc).
   - Primary UX surface: PR comments, PR review inline comments, merge-gating checks.

2. **Cerberus Cloud becomes a separate managed service** (separate repo):
   - Distributed as a **GitHub App** (single install surface).
   - Billing via **GitHub Marketplace**.
   - Runs the same review/triage logic server-side and posts results back to GitHub.
   - Enforces **metering** (rate limits / budgets) and **org controls** (policy, auditing).

3. **Interfaces become the product boundary**:
   - The reviewer JSON schema (verdict + findings) is treated as a stability contract.
   - “Finding → triage → fix PR” is the shared loop across modules and trigger sources.

4. **Observability is staged**:
   - Near-term: integrate external signals (Sentry/PagerDuty/Datadog/etc) as triage triggers.
   - Long-term: only replace incumbents after we have pull and a clearly better UX.

## Consequences

Positive:
- OSS stays simple, legible, and self-hostable.
- Cloud can add managed-only capabilities (billing, quotas, org policy) without contaminating OSS codepaths.
- Roadmap remains coherent: one GitHub-native agentic “quality loop”.

Negative:
- Two distributions to maintain (Action + App).
- Requires strong schema discipline to avoid drift between OSS and Cloud.

## Alternatives Considered

- Build everything as one SaaS and deprecate the Action: rejected (locks us into ops + UI too early; breaks OSS ethos).
- Stay OSS-only: rejected (no clear path to sustainable margins; harder to deliver “it just works” onboarding).
- Multiple apps (review app, triage app, observability app): rejected for now (too much install/billing fragmentation).

