# Issue 446 Walkthrough: Decommission Legacy Review Pipeline

## Summary

This lane removes the retired Python/Shell GitHub Actions review pipeline and leaves one supported path in the repository:

- root `action.yml`
- root `dispatch.sh`
- the Elixir engine in `cerberus-elixir/`

## Before

- The repository still shipped the old matrix review pipeline, its helper actions, and its Python test/config surface.
- Consumer docs and templates described multiple conflicting installation paths.
- CI validated a deleted architecture instead of the current API-dispatch contract.

## After

- The root action is now the thin API client.
- `dispatch.sh` is the only production shell entrypoint for review dispatch.
- Obsolete review actions, scripts, Python tests, and Python-only repo config are removed.
- Consumer docs, maintainer docs, templates, and self-review/CI workflows now describe and verify the API-dispatch path.

## Verification

```bash
find scripts/ -name '*.py' -o -name '*.sh' 2>/dev/null | wc -l
find . -name 'action.yml' -not -path './.git/*' | wc -l
head -3 action.yml | grep -q "Cerberus Review (API)"
python3 -m pytest tests/ 2>&1 || true
python3 -m yamllint action.yml .github/workflows/*.yml templates/*.yml
node --check bin/cerberus.js
shellcheck dispatch.sh cerberus-elixir/deploy-sprite.sh cerberus-elixir/test/release_contract.sh
cd cerberus-elixir && mix format --check-formatted
cd cerberus-elixir && mix test
```

## Residual Risk

- Several historical ADRs and walkthroughs still describe the retired matrix pipeline. They are no longer linked as current docs, but they remain in-repo as historical artifacts.
- The next migration lane (`#447`) still needs to move the Elixir project to repo root.
