# QA

## Local Checks

```bash
cargo test --workspace
shellcheck cerberus-elixir/deploy-sprite.sh \
  cerberus-elixir/test/release_contract.sh \
  fixtures/harnesses/command-reviewer.sh \
  fixtures/harnesses/live-peer-reviewer.sh

cd cerberus-elixir
mix test
mix format --check-formatted
```

## Consumer Smoke Check

1. Run `cerberus-cli init` from a source checkout, or manually install
   `templates/consumer-workflow-reusable.yml` into a test repository.
2. If you installed the workflow manually, set `CERBERUS_API_KEY` as a
   repository secret.
3. If you are not using the hosted default, set `cerberus-url` in the workflow.
4. Open a non-draft PR from the same repository.
5. Confirm the workflow runs the root action and receives a verdict.

## Expected Behavior

- Fork PRs skip with `SKIP`.
- Draft PRs skip with `SKIP`.
- Missing `CERBERUS_API_KEY` fails fast.
- `FAIL` verdicts fail the workflow when `fail-on-verdict` is `true`.
