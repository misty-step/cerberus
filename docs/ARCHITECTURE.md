# Cerberus Architecture

Cerberus now has one public review path:

1. a thin GitHub Action client at repo root
2. the Elixir review engine in `cerberus-elixir/`

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
