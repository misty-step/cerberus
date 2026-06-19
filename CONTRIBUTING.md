# Contributing

Cerberus now has two active code surfaces:

- the Rust-backed GitHub Action client at repo root
- the Elixir review engine in `cerberus-elixir/`

If you change the consumer contract, update the docs and templates in the same lane.

## Local Setup

```bash
cargo test --workspace
node --check bin/cerberus.js
shellcheck cerberus-elixir/deploy-sprite.sh \
  cerberus-elixir/test/release_contract.sh \
  fixtures/harnesses/command-reviewer.sh \
  fixtures/harnesses/live-peer-reviewer.sh

cd cerberus-elixir
mix deps.get
mix test
mix format --check-formatted
```

## Change Rules

- Keep the root action thin. Engine logic belongs in `cerberus-elixir/`, not in GitHub workflow glue.
- Update `README.md`, `CLAUDE.md`, and `templates/consumer-workflow-reusable.yml` whenever the action contract changes.
- Preserve `defaults/` and `pi/agents/` unless the engine contract actually changed.
- Prefer deleting dead compatibility layers over extending them.

## Typical Lanes

### GitHub Action / Dispatch

Touched files usually include:

- `action.yml`
- `crates/cerberus-cli/src/main.rs`
- `templates/consumer-workflow-reusable.yml`
- `bin/cerberus.js`
- `README.md`

Verify with:

```bash
cargo test -p cerberus-cli --test github_action_entrypoint
cargo test -p cerberus-cli --test github_action_dispatch
node --check bin/cerberus.js
```

### Elixir Engine

Touched files usually live under `cerberus-elixir/`.

Verify with:

```bash
cd cerberus-elixir
mix test
mix format --check-formatted
```
