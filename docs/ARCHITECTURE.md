# Cerberus Architecture

Cerberus now has one public review path:

1. the root CLI command `cerberus review --repo <path> --base <ref> --head <ref>`

## Request Flow

```text
cerberus review --repo --base --head
    │
    ▼
Cerberus.Command / Cerberus.CLI
    │
    ▼
Cerberus.ReviewWorkspace
    │
    ▼
Cerberus.Router
    │
    ▼
Cerberus.Review
    │
    ├── reviewer execution
    ├── verdict aggregation
    └── terminal rendering
```

## Design Rules

- Keep the supported surface CLI-only.
- Keep review orchestration in Elixir, not in external bootstrap glue.
- Keep product data in `defaults/` and `pi/agents/`.
- Delete compatibility layers once the engine owns the behavior.

## Active Modules

### Root CLI Application

Responsibilities:

- parse top-level CLI commands
- prepare isolated review workspaces from local refs
- route and run reviewers
- aggregate verdicts
- render human-readable terminal output

## Historical Note

Older documents and walkthroughs may still reference retired GitHub Action, API, or deployment lanes. Those are historical artifacts, not current architecture.
