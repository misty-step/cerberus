# Vision

## One-Liner
Rust review engine for source-agnostic changes: multi-perspective AI review in,
versioned review artifact out.

## North Star
Make Cerberus the composable review core used by the Misty Step stack. The
default caller will often be a GitHub pull request, but the engine must only
care that a caller submitted a change, context, policy, and a desired artifact
contract.

## Position

Cerberus differentiators:
- **Composable core**: Rust library and CLI usable by CI, event planes, and
  product-specific orchestrators through adapters.
- **Source-agnostic review**: pull request is one adapter, not the engine's
  ontology.
- **Multi-perspective review**: specialized reviewer agents selected per
  change, not a single generic pass.
- **Model/provider/harness diversity**: reviewer configs can vary by model,
  provider, harness, perspective, and budget.
- **Structured artifact first**: markdown, inline comments, and summaries are
  renderers over `ReviewRunArtifact`, not the source of truth.
- **Measured reviewer evolution**: Daedalus promotes reviewer configurations
  into Cerberus only after eval evidence.

## Packaging

- **Rust crate/workspace**: core engine, schemas, and adapter SDK.
- **CLI**: local/CI review runner and artifact validator.
- **Service adapter**: optional HTTP API preserving the current dispatch/poll
  flow without becoming the core boundary.
- **GitHub adapter**: acquisition and rendering compatibility for the existing
  action path.

## Target User
Internal and external engineering teams that need high-signal automated review
without coupling their orchestration plane to a specific product runtime.

## Roadmap

### v0: Rust Contract Spine
Define `ReviewRequest`, `ReviewConfig`, `ReviewerArtifact`, and
`ReviewRunArtifact` schemas with fixtures and validators. Port only enough
legacy behavior to prove request -> artifact deterministically.

### v1: Review Engine Parity
Port routing, reviewer execution, aggregation, finding dedupe, cost accounting,
coverage/degrade policy, and renderers from the useful Cerberus and ThinkTank
donor surfaces.

### v2: Caller Adapters
Make Bitterblossom and Olympus consume the same Cerberus contract through
separate adapters. Neither caller imports or references the other.

### v3: Daedalus Promotion Loop
Import Daedalus-certified reviewer configurations with benchmark evidence,
holdout discipline, and rollback metadata.

## Design Principles

- **Agentic, not dashboard** — workflows and PR comments, not web UIs
- **Unix philosophy** — each module does one thing well, composes with others
- **Deep modules** (Ousterhout) — simple interfaces, complex internals
- **Rust by default** — durable core logic belongs in Rust
- **Model-agnostic** — any model via OpenRouter, per-reviewer diversity
- **Contract first** — source adapters and renderers depend on schemas, not
  private engine internals
- **Zero-config defaults, deep config when needed**

---
*Last updated: 2026-06-18*
*Updated during: Rust resurrection shaping*
