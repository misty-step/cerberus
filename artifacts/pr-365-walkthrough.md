# PR Walkthrough: Issue #365

## Goal

Keep the shipped verdict composite action from failing before verdict synthesis when `scripts/read-defaults-config.py` imports `yaml`.

## Before

- `verdict/action.yml` provisioned Python 3.12 but did not install `PyYAML`.
- The first bootstrap read of `defaults/config.yml` happened in that under-provisioned environment.
- Downstream repositories could get a false-red required `review / Cerberus` check even though review shards had already completed.

## After

- `verdict/action.yml` now installs `PyYAML` immediately after `actions/setup-python`.
- The install happens before the action invokes `scripts/read-defaults-config.py`.
- `tests/test_verdict_action.py` now locks that ordering so the verdict bootstrap dependency cannot silently drift out again.

## Verification

- RED:
  - `uvx --from pytest pytest tests/test_verdict_action.py tests/test_defaults_config_reader.py -q`
  - Outcome before the action fix: the new verdict-action regression failed because `pip install pyyaml --quiet` was missing, and the defaults-config reader CLI reproduced `ModuleNotFoundError: No module named 'yaml'` in a clean runner.
- GREEN:
  - `uvx --with pyyaml --from pytest pytest tests/test_verdict_action.py tests/test_defaults_config_reader.py -q`
  - Outcome after the fix: `32 passed in 0.76s`
  - `uvx ruff check tests/test_verdict_action.py`
  - Outcome: `All checks passed!`

## Persistent Check

`uvx --with pyyaml --from pytest pytest tests/test_verdict_action.py tests/test_defaults_config_reader.py -q`

## Residual Risk

- This lane fixes the concrete bootstrap dependency gap in the shipped verdict action.
- `make validate` still depends on a separately provisioned local Python toolchain in this worktree, so branch verification stays focused on the touched verdict/bootstrap surface.
