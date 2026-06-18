# Cerberus Architecture

Cerberus now has one public review path:

1. a thin GitHub Action client at repo root
2. the Elixir review engine in `cerberus-elixir/`

## Resurrection Target

The current path above is the legacy compatibility surface. ADR 006 changes the
long-term architecture target to a Rust review-artifact core:

```text
ReviewRequest.v1 + ReviewConfig.v1 + ReviewPolicy.v1
    -> Cerberus Rust core
    -> ReviewRunArtifact.v1
```

The GitHub Action, hosted API, and dispatch/poll flow may wrap that core as
adapters, but they do not define the core boundary. Bitterblossom and Olympus
remain independent callers through the same contract; neither caller should know
about the other.

`crates/cerberus-adapter` is the consumer-side SDK and fixture home for that
contract. It may provide request builders, caller receipt examples, and artifact
projections, but it must not move caller-owned runtime concerns into
`cerberus-core`.

## Request Flow

```text
pull_request event
    │
    ▼
action.yml
    │
    ▼
dispatch.sh
    │
    ├── POST /api/reviews
    ├── poll GET /api/reviews/:id
    └── emit verdict output

cerberus-elixir/
    ├── accepts review request
    ├── runs reviewer agents
    ├── aggregates verdict
    └── persists run state
```

## Design Rules

- Keep the GitHub Action client thin.
- Keep review orchestration in Elixir, not in workflow glue.
- Keep product data in `defaults/` and `pi/agents/`.
- Delete compatibility layers once the engine owns the behavior.

## Active Modules

### Root Action

- `action.yml`
- `dispatch.sh`
- `templates/consumer-workflow-reusable.yml`
- `bin/cerberus.js`

Responsibilities:

- validate basic PR context
- dispatch to the API
- poll until completion
- expose workflow outputs

### Rust Adapter SDK

Lives in `crates/cerberus-adapter/`.

Responsibilities:

- build and validate caller-shaped `ReviewRequest.v1` values
- prove the local fixture contract shape for Bitterblossom and Olympus without
  cross-caller references
- project `ReviewRunArtifact.v1` into caller-owned receipt/posting shapes
- guard fixture text against cross-caller references

Non-responsibilities:

- Bitterblossom task queues, retries, budgets, or run ledgers
- Olympus Argus activation gates, stale-head suppression, marker dedupe, caps,
  or GitHub posting
- live acquisition from either caller repository

### Elixir Engine

Lives in `cerberus-elixir/`.

Responsibilities:

- accept review requests
- route / run reviewers
- aggregate verdicts
- expose HTTP endpoints
- persist run state

## Historical Note

Older documents and walkthroughs may still reference the retired Python/Shell matrix pipeline. Those are historical artifacts, not current architecture.
