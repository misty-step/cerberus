# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Cerberus is a multi-agent AI code review system shipped as a GitHub Action. Five parallel KimiCode CLI reviewers (powered by Kimi K2.5) each analyze a PR diff from a specialized perspective, then a council action aggregates their verdicts into a single merge-gating check.

## Architecture

```text
PR opened/synced
    │
    ▼
consumer workflow (.github/workflows/cerberus.yml)
    │
    ├── matrix job × N reviewers (parallel, fail-fast: false)
    │   └── uses: misty-step/cerberus@v1  (action.yml)
    │       ├── fetch PR diff/context
    │       ├── run-reviewer.sh   (prompt + kimi invocation)
    │       ├── parse-review.py   (extract + validate JSON verdict)
    │       ├── post-comment.sh   (optional per-reviewer PR comment)
    │       └── upload verdict artifact
    │
    └── verdict job (needs: review, if: always())
        └── uses: misty-step/cerberus/verdict@v1  (verdict/action.yml)
            ├── download verdict artifacts
            ├── aggregate-verdict.py  (override handling + council decision)
            └── post council comment + optional fail on FAIL
```

The consumer defines the reviewer matrix in its own workflow. This repository provides only the reusable actions and support files.

Inside the review action, `CERBERUS_ROOT` is set to `${{ github.action_path }}`. Scripts, agent configs, and templates are resolved relative to that root (`scripts/`, `agents/`, `templates/`, `defaults/`).

### The Five Reviewers

| Name | Perspective | Shell Access | Focus |
|------|-------------|-------------|-------|
| APOLLO | correctness | no | Logic bugs, edge cases, type mismatches |
| ATHENA | architecture | no | Design patterns, module boundaries |
| SENTINEL | security | no | Threat model, injection, auth flaws |
| VULCAN | performance | no | Runtime efficiency, scalability |
| ARTEMIS | maintainability | no | DX, readability, future maintenance |

Shell access is toggled per agent via `exclude_tools` in the YAML config.

### Key Files

- `action.yml` - review composite action entrypoint
- `verdict/action.yml` - council verdict composite action entrypoint
- `defaults/config.yml` - council settings, reviewer list, verdict thresholds, override rules
- `agents/<perspective>.yaml` - KimiCode agent config (extends default, sets system prompt path, tool restrictions)
- `agents/<perspective>-prompt.md` - system prompt defining identity, focus areas, anti-patterns, and JSON output schema
- `templates/review-prompt.md` - user prompt template with `{{PLACEHOLDER}}` vars filled from PR context
- `templates/consumer-workflow.yml` - recommended workflow for downstream repositories
- `scripts/run-reviewer.sh` - orchestrates one reviewer: builds prompt, writes TOML config, invokes `kimi --quiet`
- `scripts/parse-review.py` - extracts last ` ```json ` block, validates required fields/types
- `scripts/post-comment.sh` - formats findings as markdown, upserts comment using HTML marker for idempotency
- `scripts/aggregate-verdict.py` - reads verdict JSON artifacts, applies override logic, writes council verdict

## Verdict Logic

Each reviewer emits: `FAIL` (any critical OR 2+ major) | `WARN` (1 major OR 5+ minor OR 3+ minor in same category) | `PASS`.
Only findings from reviews with confidence >= 0.7 count toward these thresholds.

Council: `FAIL` on a critical reviewer FAIL or 2+ reviewer FAILs (unless overridden) | `WARN` on any WARN or a single non-critical FAIL | `PASS` otherwise.

Override: `/council override sha=<sha>` comment on PR with reason. SHA must match HEAD. Actor constraints per `defaults/config.yml`.

## Output Schema

Every reviewer must end with a JSON block containing: `reviewer`, `perspective`, `verdict`, `confidence` (0-1), `summary`, `findings[]` (each with severity/category/file/line/title/description/suggestion), `stats` (files_reviewed, files_with_issues, critical, major, minor, info).

## KimiCode CLI Constraints

- Provider type **must** be `kimi` (not `openai_legacy`) when `--thinking` is enabled - `openai_legacy` breaks on tool-use + thinking
- `--config` = inline TOML text, `--config-file` = file path (not interchangeable)
- `--quiet` = `--print --output-format text --final-message-only` (parseable single output)
- `stream-json` output format escapes newlines, breaking JSON extraction - use `--quiet` instead
- Moonshot API base URL: `https://api.moonshot.ai/v1` (not `.cn`)

## Testing Locally

```bash
# Run test suite
pip install pytest
python3 -m pytest tests/ -v

# Or use the helper script
./tests/run-tests.sh

# Lint
shellcheck scripts/*.sh
python3 -m py_compile scripts/parse-review.py
python3 -m py_compile scripts/aggregate-verdict.py
```

End-to-end testing requires pushing to a branch and having a target repo use `misty-step/cerberus@<branch>`. Current test target: `misty-step/moonbridge`.

## GitHub Actions Gotchas

- `gh pr view --json comments` returns GraphQL node IDs - use `gh api repos/.../issues/N/comments` for REST numeric IDs
- REST issue comment payloads expose actor as `user.login`; `author.login` is GraphQL-specific
- When testing workflow `--jq` snippets in YAML, assert key field usage (e.g. `.user.login`) without exact full-string matching to avoid whitespace-only test failures
- `pull-requests: write` permission is required for posting PR comments
- Secrets are snapshotted per workflow run - push a new commit to pick up secret changes
- `set -e` in steps means any command failure stops the step; `run-reviewer.sh` uses `set +e` around kimi invocation deliberately

## Deployment

Consumers reference this repo as a GitHub Action. See `templates/consumer-workflow.yml` for the recommended setup. The only required secret is `MOONSHOT_API_KEY`.

Tagged releases follow semver. Consumers pin to `@v1` for automatic patch updates.
