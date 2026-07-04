# OpenCode substrate operations

Cerberus treats OpenCode as a production substrate, not an ambient developer
tool. The exact CLI version is pinned in `config/opencode-version.json`; any
`--harness opencode` run probes `opencode --version` before launching the
reviewer and fails before model execution when the installed version drifts.

## Live smoke key

The scheduled live smoke uses the GitHub secret
`CERBERUS_SMOKE_OPENROUTER_KEY`. Operators must provision this as a narrowly
scoped, spend-capped OpenRouter key for this smoke only. Do not reuse a broad
developer `OPENROUTER_API_KEY` or a key shared with another service.

If the secret is absent, the workflow exits successfully and writes a notice so
new forks and fresh repositories stay green until the operator provisions the
key.

## Bumping the OpenCode pin

1. Install the candidate version locally.
2. Update `config/opencode-version.json` so `version` and `install` name the
   same exact version.
3. Run the loud-fail demo by pointing Cerberus at an older fake OpenCode binary;
   the error must name the expected version, observed version, pin file, and
   this bump procedure.
4. Run `./scripts/opencode-live-smoke.sh` with a spend-capped
   `CERBERUS_SMOKE_OPENROUTER_KEY`.
5. Run `./scripts/verify.sh`.
6. Open a PR with the smoke transcript or issue/run URL in the body.

The bump is intentionally a code-reviewable PR because an OpenCode contract
change can break production while the fixture gate stays green.
