# CLAUDE.md

This repository now has one supported delivery path:

- root `action.yml` is the Cerberus GitHub Action
- root `dispatch.sh` is its polling client
- `cerberus-elixir/` contains the review engine and HTTP API

The retired Python/Shell matrix pipeline has been removed from the active repo surface.

## Architecture

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
    ├── API endpoint
    ├── reviewer orchestration
    ├── verdict aggregation
    └── persistence / telemetry
```

## Key Files

- `action.yml` - thin GitHub Action entrypoint
- `dispatch.sh` - preflight + API dispatch + polling loop
- `cerberus-elixir/lib/cerberus/` - engine modules
- `cerberus-elixir/config/` - runtime config
- `defaults/config.yml` - product/model defaults consumed by the engine
- `pi/agents/*.md` - reviewer personas
- `templates/consumer-workflow-reusable.yml` - recommended consumer workflow
- `bin/cerberus.js` - scaffolder CLI

## Local Commands

```bash
node --check bin/cerberus.js
shellcheck dispatch.sh

cd cerberus-elixir
mix deps.get
mix test
mix format --check-formatted
```

## Default Operating Frame

For most Cerberus work, use these companion frames by default:

- `context-engineering`
- `llm-infrastructure`
- `harness-engineering`

If one does not apply, say why briefly.

## LLM-First Rule

For semantic tasks such as review classification, prioritization, or intent mapping, prefer LLM reasoning over deterministic heuristics. Use deterministic logic only for strict syntax, schema, safety, or protocol enforcement.
