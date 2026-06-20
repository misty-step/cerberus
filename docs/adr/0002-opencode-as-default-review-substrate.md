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
