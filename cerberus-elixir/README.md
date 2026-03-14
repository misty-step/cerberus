# Cerberus Elixir

Foundational OTP scaffold for the Cerberus engine migration.

## Scope

This subproject intentionally stops at the application boundary:

- bootable supervision tree
- repository-backed config and prompt loading
- SQLite schema bootstrap
- stub `Cerberus.BB.Worker` behaviour implementation

It does not yet include reviewer execution, GitHub integration, or Phoenix.

## Verification

```bash
cd cerberus-elixir
mix deps.get
mix compile
mix test
```
