# PR Walkthrough: Issue #416

## Goal

Finish the post-ADR-005 cleanup by removing archived Cerberus products from active dogfood configuration in this repo and by fixing the monorepo-root `.dockerignore` to ignore the archived location instead of deleted live paths.

## Before

- `defaults/dogfood.yml` still treated `misty-step/cerberus-cloud` as a live core dogfood repo even though ADR 005 archived Cerberus Cloud and Cerberus Web.
- The dogfood presence tests did not guard against archived repos re-entering the active benchmark target set.
- `/Users/phaedrus/Development/cerberus-mono/.dockerignore` still referenced `cerberus-web/` and `cerberus-cloud/node_modules/` at the old root paths rather than the `_archived/` tree.

## After

- `defaults/dogfood.yml` now tracks only active core repos.
- `tests/test_dogfood_presence.py` now asserts that archived repos are excluded from active dogfood targets.
- `/Users/phaedrus/Development/cerberus-mono/.dockerignore` now ignores `_archived/`, which covers both archived products at their actual location.

## Verification

- Repo checks:
  - `python3 -m pytest tests/test_dogfood_presence.py -q`
  - Outcome: `27 passed`
  - `make validate`
  - Outcome: `1894 passed, 1 skipped`; `ruff`, `shellcheck`, and `cerberus-elixir` checks all passed
- Root cleanup checks:
  - `rg -n "cerberus-cloud|cerberus-web" /Users/phaedrus/Development/cerberus-mono/AGENTS.md /Users/phaedrus/Development/cerberus-mono/CLAUDE.md /Users/phaedrus/Development/cerberus-mono/.dockerignore /Users/phaedrus/Development/cerberus-mono/.github 2>/dev/null`
  - Outcome: no matches after the `.dockerignore` fix

## Persistent Check

`make validate`

## Residual Risk

- Historical benchmark docs and ADRs still mention `cerberus-cloud` and `cerberus-web` on purpose; this lane only removes them from active config and root ignore paths.
- The monorepo-root `.dockerignore` change lives outside this repo’s git boundary, so reviewers need the walkthrough note to understand the full issue closure evidence.
