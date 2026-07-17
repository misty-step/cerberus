# ADR 0002: Use OpenCode as the Default Review Substrate

Date: 2026-06-19

Status: Accepted

## Context

Cerberus needs an agent execution substrate for the master reviewer. The Rust
application owns the stable product boundary: `ReviewRequest.v1`, runtime
policy, context capabilities, execution receipts, artifact validation, and
rendering. The substrate owns agentic execution inside that boundary.

The substrate report compared current coding-agent systems for production code
review. Its core finding is that OpenCode is a better fit than a terminal-first
wrapper because OpenCode is server/session-first: a caller can create sessions
programmatically, attach tools and policy, collect structured events, and run
concurrent reviewer lanes without screen-scraping an interactive CLI.

OMP remains valuable. It has strong local coding ergonomics, worktree-oriented
subagents, broad tooling, and enough headless surface to be a useful fallback
and experimentation path. Its design center is still closer to an expert local
coding environment than a durable service kernel for an organization-wide
review runner.

## Decision

OpenCode is the default production-oriented Cerberus review substrate. OMP
remains supported as a local fallback. The fixture harness remains the
deterministic verifier.

The CLI default is therefore:

```text
cerberus review --harness opencode
```

Cerberus still defines exactly one predefined reviewer: the master reviewer.
OpenCode's session and subagent support does not change that product rule. The
master may decide at runtime whether to launch focused lanes, but Cerberus
does not predefine static reviewer personas in Rust.

## Consequences

OpenCode gets the first production hardening pass:

- request and prompt material are transported through private files;
- execution plans redact private prompt paths;
- diff-only requests run in packet workspaces rather than the repository root;
- child processes receive a scrubbed environment with an explicit allowlist;
- artifacts must round-trip through `ReviewArtifact.v1` validation.

OMP must continue to pass the same harness contract, but it is not the primary
production path. Any OMP-specific feature must earn its way through the common
request, artifact, receipt, and verifier contracts rather than widening
Cerberus around terminal-local affordances.

The decision also keeps model and harness evaluation outside Cerberus. Daedalus
or another laboratory may evaluate OpenCode, OMP, Codex, Claude, Goose, or
model families against Cerberus artifacts, then feed recommendations back into
configuration. Cerberus records enough receipts for those systems to score
runs; it does not become the evaluation lab.

## Alternatives Considered

Use OMP as the default substrate.

This would align with local power-user workflows and rich tool support, but it
would make the central review runner inherit a terminal-first execution shape.
That is a poor fit for durable sessions, structured event capture, retries,
fleet operation, and future service integration.

Use Codex or Claude as the default substrate.

Both are plausible high-quality reviewer substrates, especially for shops that
standardize on one provider. Cerberus is intentionally trying to keep the
execution kernel more provider-neutral for now while owning the review contract
above it.

Build a first-party agent loop in Rust.

This maximizes control but burns the MVP on recreating tool orchestration,
session handling, model adapters, and subagent mechanics. Cerberus should own
the review contract and harness boundary first.

## Revisit If

- OpenCode removes or weakens the session/server surface Cerberus depends on.
- OMP grows a durable service-oriented execution surface that beats OpenCode
  on structured events, isolation, and control-plane integration.
- A managed substrate proves materially better on self-review quality,
  artifact validity, cost, or latency in upstream evaluations.
- Cerberus needs capabilities that cannot fit behind the common
  `ReviewHarness` contract without making OpenCode-specific assumptions leak
  into public request or artifact schemas.

## Guard for a Future Default Flip (added 2026-07-17)

`OPERATOR-CHARTER-2026-07-17.md` puts OMP back in scope as a first-class,
subscription-backed local runtime path, alongside a local control plane this
ADR did not originally anticipate. This section does not flip the default —
`--harness opencode` remains it — it names the exact bar a future superseding
ADR must clear before it can.

Phase 0 (`docs/evidence/omp-phase0-2026-07-17.md`,
`docs/plans/productization-2026-07-17.md`) already closed the reliability gap
that motivated this ADR's original OMP hesitation: OMP v17.0.2 now has a
pinned, fail-closed, `--mode json` headless path with repeated live lifecycle
proof and one request-bound `ReviewArtifact.v1` from the exact public
Cerberus entrypoint. That evidence answers "is OMP headless reliable," not
"should OMP be the default."

A future ADR may supersede this one and flip the default only when all of
the following hold, each with its own dated evidence, not narrative claims:

1. Phase 1's mandatory-seat, identity-validation, and subscription-first
   policy (ADR 0004) is implemented and live-proven under OMP, not only
   fixture-proven.
2. OpenCode's fallback path is proven viable under the same subscription-
   first/OpenRouter-denied-by-default policy — a fallback that only works
   through the policy exception it exists to guard against is not a real
   fallback.
3. `spec.md` and `VISION.md` are revised in the same PR as the superseding
   ADR, per `AGENTS.md` red line 4 — this ADR's own "Substrate order for
   Cerberus" language in `spec.md` is locked contract, not this file alone.
4. The comparison in "Alternatives Considered" above (durable sessions,
   structured events, retries, fleet operation) is re-run against OMP's
   actual Phase 1 control-plane surface, not its Phase 0 headless-only shape.