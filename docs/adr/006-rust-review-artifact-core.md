# ADR 006: Rust Review-Artifact Core

- Status: Accepted
- Date: 2026-06-18
- Deciders: Cerberus maintainers
- Related: ADR 004, `docs/shaping/rust-review-engine-resurrection.md`,
  `backlog.d/001-rust-review-engine-contract.md`

## Context

Cerberus is being resurrected after the legacy review pipeline was archived.
The current repository still has GitHub-shaped API and pipeline edges:
`POST /api/reviews`, polling, GitHub token forwarding, PR context fetches, PR
reviews, comments, and check updates. Those surfaces made sense for the
Elixir-hosted GitHub Action product, but they are too wide and too coupled for
the next version of Cerberus.

The useful core is narrower. The existing engine already points at the better
module boundary: accept diff/context, choose a reviewer panel, run reviewers,
aggregate verdicts, dedupe findings, track cost, and emit structured review
results.

Adjacent systems clarify the boundary:

- Bitterblossom owns event-plane concerns: triggers, ledgers, queues, retries,
  budgets, run records, and recurring execution.
- Olympus owns Adminifi-specific Argus policy: activation gates, stale-head
  suppression, marker dedupe, caps, and GitHub posting.
- Daedalus owns reviewer research: arenas, score distributions, promotion
  evidence, launch contracts, and rollback metadata.
- ThinkTank is review-bench donor material and a decommission candidate for
  production review execution.

## Decision

Cerberus's durable core will be a Rust review-artifact engine, not a workflow
plane or hosted service shell.

The core interface is:

```text
ReviewRequest.v1 + ReviewConfig.v1 + ReviewPolicy.v1 -> ReviewRunArtifact.v1
```

The core may expose Rust library APIs and a CLI. An HTTP dispatch/poll service,
GitHub Action, scaffolder, or hosted deployment may wrap the core as an adapter,
but those adapters do not define the engine boundary.

The core owns:

- source-agnostic review request schemas
- reviewer configuration schemas
- reviewer execution harness abstraction
- reviewer artifacts
- verdict aggregation
- finding dedupe
- coverage and degraded-run policy
- token/cost accounting
- artifact renderers and projections

The core does not own:

- event ingress
- queueing
- run ledgers
- retries
- budget enforcement outside a single review policy
- GitHub posting authority
- stale-head suppression
- marker dedupe
- hosted service deployment
- reviewer-config discovery or benchmark search

Bitterblossom and Olympus may each call Cerberus through the same contract, but
must not know about or depend on each other. Daedalus may export measured
reviewer configuration packets that Cerberus can validate and import. ThinkTank
review artifacts may be migrated, but Cerberus must not shell out to ThinkTank
for normal production review execution.

## Consequences

Positive:

- The engine boundary is small enough to become a deep Rust module.
- GitHub remains important without becoming the engine's ontology.
- Bitterblossom and Olympus stay independent callers.
- Daedalus can improve reviewer quality without turning Cerberus into an eval
  workbench.
- Legacy Elixir behavior can be ported by fixture, then deleted or archived
  deliberately.

Negative:

- The current hosted API/action path becomes compatibility work, not the center
  of the rewrite.
- Existing docs and user expectations around "GitHub-native product" need
  migration.
- Adapter fixtures are required before callers can safely switch over.

Maintenance rules:

- A Rust core crate must not import GitHub, HTTP server, queue, or deployment
  concerns.
- New caller integrations must prove they consume the contract without
  cross-caller references.
- Legacy code is kept only while it is donor material or compatibility surface
  with a named retirement path.

## Alternatives Considered

1. Rebuild the Elixir hosted API in Rust first.
   - Rejected: preserves the wrong boundary and risks making Cerberus another
     workflow plane.
2. Make Bitterblossom the review engine.
   - Rejected: Bitterblossom is the event plane; putting review judgment there
     violates its "no judgment in the spine" boundary.
3. Keep ThinkTank as the long-term review engine.
   - Rejected: ThinkTank is a bench launcher and artifact donor, not the
     product-quality review core.
4. Let Daedalus own runtime review.
   - Rejected: Daedalus is the foundry and evaluator; production review requires
     a stable engine and caller-owned authority boundaries.
