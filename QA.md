# QA

## Local Checks

```bash
mix compile --warnings-as-errors
mix test
mix format --check-formatted
mix escript.build
```

## CLI Smoke Check

1. Build the packaged CLI with `mix escript.build`.
2. Set `CERBERUS_OPENROUTER_API_KEY` or `OPENROUTER_API_KEY`.
3. From outside the target repository, run:

   ```bash
   ./cerberus review --repo /path/to/repo --base main --head HEAD
   ```

4. Confirm Cerberus prints a human-readable verdict and summary for the requested range.

## Expected Behavior

- `cerberus --help` shows only the CLI command inventory.
- `cerberus review --help` documents `--repo`, `--base`, and `--head`.
- Retired commands such as `init`, `start`, `server`, and `migrate` fail clearly.
- Missing OpenRouter credentials fail at review time without starting any server.
