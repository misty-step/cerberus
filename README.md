# Cerberus

Cerberus is a local CLI for reviewing a repository change range.

## Quick Start

```bash
mix deps.get
mix escript.build

./cerberus review --repo /path/to/repo --base main --head HEAD
```

You can also run the Mix task directly:

```bash
mix cerberus.review --repo /path/to/repo --base main --head HEAD
```

## Environment

Required for live LLM-backed reviews:

- `CERBERUS_OPENROUTER_API_KEY` or `OPENROUTER_API_KEY`

Optional:

- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_SECRET_KEY`
- `LANGFUSE_HOST`

Cerberus no longer requires a GitHub Action, HTTP API, server process, or local port binding.

## Repository Layout

- `mix.exs`: root Mix project and packaged CLI definition
- `lib/`: CLI, review core, planner, reviewers, and supporting runtime modules
- `config/`: runtime configuration
- `defaults/`: shipped reviewer/model defaults
- `pi/agents/`: reviewer prompts
- `templates/`: review prompt templates
- `test/`: automated validation

## Local Verification

```bash
mix compile --warnings-as-errors
mix test
mix format --check-formatted
mix escript.build
./cerberus --help
```

## Docs

- [Architecture](docs/ARCHITECTURE.md)
- [Terminology](docs/TERMINOLOGY.md)
- [Docs index](docs/README.md)

## Historical Note

Older walkthroughs and ADRs may still mention retired GitHub Action, API, or deployment lanes. Treat those references as historical only.
