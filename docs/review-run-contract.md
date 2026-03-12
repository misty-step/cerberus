# Review-Run Contract

Cerberus review execution boots from a provider-agnostic `review-run.json` contract.
The GitHub Action writes this contract before invoking the engine runner. Future
orchestrators should target the same contract instead of replaying GitHub-specific
bootstrap env wiring.

## Purpose

- Keep the engine input narrow and explicit.
- Let GitHub Actions remain the first OSS distribution without leaking raw GitHub
  env names through the runtime boundary.
- Preserve compatibility for older/local callers that still use legacy `GH_*`
  env fallbacks.

## Contract Shape

| Field | Type | Meaning |
| --- | --- | --- |
| `version` | int | Contract schema version. Current value: `1`. |
| `platform` | string | Orchestrator family. Current GitHub lane writes `github`. |
| `repository` | string | Canonical repository identity (`owner/name`). |
| `pr_number` | int | Pull request identity for the run. |
| `head_ref` | string | PR head branch/ref. |
| `base_ref` | string | PR base branch/ref. |
| `diff_file` | string | Path to the fetched diff input for review. |
| `pr_context_file` | string | Path to the fetched PR metadata JSON (`title`, `author`, `headRefName`, `baseRefName`, `body`). |
| `workspace_root` | string | Working directory used for the run. |
| `temp_dir` | string | Output root for runtime artifacts (`<perspective>-output.txt`, parse sidecars, prompt capture, telemetry, verdict staging). |
| `github.repo` | string | GitHub repo scope for runtime helpers such as `github_read`. |
| `github.pr_number` | int | GitHub PR scope for runtime helpers. |
| `github.token_env_var` | string | Env var name that carries GitHub auth into the isolated runtime. |

## GitHub Action Mapping

The current action maps cleanly onto the contract:

1. `action.yml` invokes `scripts/fetch-pr-bootstrap.py`, which fetches `pr.diff` and `pr-context.json` through `scripts/lib/github_platform.py`.
2. `scripts/bootstrap-review-run.py` writes `review-run.json`.
3. `scripts/run-reviewer.py` loads the contract, reads diff/context from it, and
   reconstructs GitHub runtime env for the isolated Pi process from
   `github.repo`, `github.pr_number`, and `github.token_env_var`.
4. `scripts/parse-review.py` and later verdict steps continue consuming artifacts
   from `temp_dir` without needing raw GitHub bootstrap envs.

## Compatibility

- Preferred path: `CERBERUS_REVIEW_RUN=/path/to/review-run.json`
- Compatibility-only fallbacks remain for existing direct callers:
  - `GH_DIFF_FILE` / `GH_DIFF`
  - `GH_PR_CONTEXT` or inline `GH_PR_*`
  - outer-process `CERBERUS_REPO` / `CERBERUS_PR_NUMBER`

Those fallbacks are not the primary GitHub Action path anymore.
