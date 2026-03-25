# CLAUDE.md

This repository now has one supported delivery path:

- the repository root Mix application and packaged CLI

The retired GitHub Action, HTTP API/server, Sprite/Fly, Node scaffolder, and shell dispatch surfaces are no longer part of the active repo surface.

## Architecture

```text
cerberus review --repo --base --head
    │
    ▼
Cerberus.Command / Cerberus.CLI
    │
    ▼
ReviewWorkspace
    │
    ▼
Router / Review / Reviewer execution
    │
    └── verdict aggregation + terminal rendering
```

## Key Files

- `mix.exs` - root Mix project and packaged CLI definition
- `lib/cerberus/` - engine and CLI modules
- `config/` - runtime config
- `defaults/config.yml` - product/model defaults consumed by the engine
- `pi/agents/*.md` - reviewer personas
- `templates/*.md` - CLI review prompt templates

## Local Commands

```bash
mix deps.get
mix compile --warnings-as-errors
mix test
mix format --check-formatted
mix escript.build
```

## Default Operating Frame

For most Cerberus work, use these companion frames by default:

- `context-engineering`
- `llm-infrastructure`
- `harness-engineering`

If one does not apply, say why briefly.

## LLM-First Rule

For semantic tasks such as review classification, prioritization, or intent mapping, prefer LLM reasoning over deterministic heuristics. Use deterministic logic only for strict syntax, schema, safety, or protocol enforcement.
