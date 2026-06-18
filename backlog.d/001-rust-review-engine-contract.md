# 001 - Rust Review Engine Contract

Status: ready
Priority: P0
Type: epic
Created: 2026-06-18

## Goal

Build the Rust contract spine for Cerberus: a library, CLI, schemas, and fixture
tests that turn a source-agnostic review request into a versioned review run
artifact.

The first interface must be simpler than the implementation:

```text
ReviewRequest + ReviewConfig -> ReviewRunArtifact
```

GitHub pull requests are supported through an adapter, but the core request must
also describe non-GitHub changes, local diffs, synthetic eval fixtures, and
future caller-owned change sources.

## Oracle

Given checked-in fixtures for:

- a local unified diff
- a GitHub pull request-shaped change
- a clean/no-finding change
- a reviewer timeout/degraded run

the Rust CLI validates each `ReviewRequest`, executes a deterministic fake
reviewer harness, emits a schema-valid `ReviewRunArtifact`, and renders markdown
from that artifact without requiring GitHub credentials or network access.

## Verification System

- `cargo test --workspace`
- `cargo run --locked -p cerberus-cli -- validate fixtures/review-request/*.json`
- `cargo run --locked -p cerberus-cli -- review --fixture fixtures/review-request/local-diff.json --out tmp/review-run`
- `cargo run --locked -p cerberus-cli -- render tmp/review-run/review-run-artifact.json`

The first implementation may use a deterministic fake reviewer harness; live LLM
execution comes after the schema and artifact lifecycle are stable.

## Scope

In scope:

- Rust workspace scaffold.
- `ReviewRequest.v1`, `ReviewConfig.v1`, `ReviewerArtifact.v1`, and
  `ReviewRunArtifact.v1` schemas.
- CLI validation, fake review execution, artifact persistence, and renderer.
- Port the durable semantics from the legacy engine: routing shape, reviewer
  records, verdict aggregation, finding dedupe, cost fields, coverage/degraded
  state, and override hooks.

Out of scope:

- HTTP server, queue, posting, or deployment inside the core crate.
- Hosted service deployment.
- GitHub posting.
- Bitterblossom/Olympus-specific runtime code.
- Daedalus optimization loop.
- Rewriting every legacy prompt before the contract is proven.

## Donor Evidence

- `docs/adr/004-review-execution-boundary.md` already names a provider-agnostic
  review-run contract as the execution boundary.
- `cerberus-elixir/lib/cerberus/engine.ex` already has the right deep-module
  shape: diff/context in, routed reviewer panel and aggregate result out.
- `cerberus-elixir/lib/cerberus/verdict/aggregator.ex` captures verdict,
  finding dedupe, cost, reserves, and override semantics worth porting.
- ThinkTank's `review/context.json`, `review/plan.json`, coverage/degrade
  artifacts, and manifest discipline are migration material, not a separate
  long-term engine.

## Child Work

1. Create the Rust workspace with `cerberus-core`, `cerberus-cli`, and
   `cerberus-schema`.
2. Write schemas and fixtures before engine behavior.
3. Implement validation and deterministic fake reviewer execution.
4. Port aggregation and finding dedupe semantics from the legacy Elixir engine.
5. Add renderer projections for markdown summary and inline-comment candidates.
6. Add a migration note mapping legacy API fields to `ReviewRequest.v1`.

## Notes

This is the first pickup. Do not start adapter work until the local fixture path
can prove request -> artifact without GitHub. The acceptance bar is an
artifact-only core; an HTTP service may wrap it later as a compatibility
adapter.
