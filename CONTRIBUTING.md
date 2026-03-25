# Contributing

Cerberus now has one supported product surface: the CLI-first Elixir application at the repository root.

If you change the CLI contract, update the active docs and validation lane in the same change.

## Local Setup

```bash
mix deps.get
mix compile --warnings-as-errors
mix test
mix format --check-formatted
mix escript.build
```

## Change Rules

- Keep the supported surface CLI-only.
- Update `README.md`, `QA.md`, and active workflow files whenever the CLI contract changes.
- Preserve `defaults/` and `pi/agents/` unless the engine contract actually changed.
- Prefer deleting dead compatibility layers over extending them.

## Typical Lanes

### CLI / Runtime

Touched files usually include:

- `lib/cerberus/command.ex`
- `lib/cerberus/cli.ex`
- `lib/cerberus/review*.ex`
- `README.md`
- `QA.md`

Verify with:

```bash
mix compile --warnings-as-errors
mix test
mix escript.build
```

### Config / Planner / Reviewers

Touched files usually live under:

- `lib/cerberus/`
- `config/`
- `defaults/`
- `pi/agents/`
- `templates/`
- `test/`

Verify with:

```bash
mix compile --warnings-as-errors
mix test
mix format --check-formatted
```
