# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Cerberus is a multi-agent AI code review system that runs as a GitHub Actions workflow. Five parallel KimiCode CLI reviewers (powered by Kimi K2.5) each analyze a PR diff from a specialized perspective, then a council job aggregates their verdicts into a single merge-gating check.

## Architecture

```
PR opened/synced
    │
    ▼
cerberus.yml workflow
    │
    ├── matrix job × 5 (parallel, fail-fast: false)
    │   ├── run-reviewer.sh  ← builds prompt from template + diff, invokes kimi CLI
    │   ├── parse-review.py  ← extracts JSON block from LLM output, validates schema
    │   └── post-comment.sh  ← upserts per-reviewer PR comment (idempotent via HTML marker)
    │
    └── verdict job (needs: review, runs if: always())
        ├── aggregate-verdict.py  ← merges verdicts, checks override comments
        └── posts council verdict comment
```

### The Five Reviewers

| Name | Perspective | Shell Access | Focus |
|------|-------------|-------------|-------|
| APOLLO | correctness | no | Logic bugs, edge cases, type mismatches |
| ATHENA | architecture | yes | Design patterns, module boundaries |
| SENTINEL | security | no | Threat model, injection, auth flaws |
| VULCAN | performance | yes | Runtime efficiency, scalability |
| ARTEMIS | maintainability | yes | DX, readability, future maintenance |

Shell access is toggled per agent via `exclude_tools` in the YAML config.

### Key Files

- `config.yml` — council settings, reviewer list, verdict thresholds, override rules
- `agents/<perspective>.yaml` — KimiCode agent config (extends default, sets system prompt path, tool restrictions)
- `agents/<perspective>-prompt.md` — system prompt defining identity, focus areas, anti-patterns, and JSON output schema
- `templates/review-prompt.md` — user prompt template with `{{PLACEHOLDER}}` vars filled from PR context
- `scripts/run-reviewer.sh` — orchestrates a single reviewer: builds prompt, writes TOML config, invokes `kimi --quiet`
- `scripts/parse-review.py` — extracts last ` ```json ` block, validates required fields/types
- `scripts/post-comment.sh` — formats findings as markdown, upserts comment using HTML marker for idempotency
- `scripts/aggregate-verdict.py` — reads verdict JSON artifacts, applies override logic, writes council verdict

## Verdict Logic

Each reviewer emits: `FAIL` (any critical OR 2+ major) | `WARN` (1 major OR 3+ minor) | `PASS`.

Council: `FAIL` if any reviewer FAILs (unless overridden) | `WARN` if any warns | `PASS` otherwise.

Override: `/council override sha=<sha>` comment on PR with reason. SHA must match HEAD. Actor constraints per `config.yml`.

## Output Schema

Every reviewer must end with a JSON block containing: `reviewer`, `perspective`, `verdict`, `confidence` (0-1), `summary`, `findings[]` (each with severity/category/file/line/title/description/suggestion), `stats` (files_reviewed, files_with_issues, critical, major, minor, info).

## KimiCode CLI Constraints

- Provider type **must** be `kimi` (not `openai_legacy`) when `--thinking` is enabled — `openai_legacy` breaks on tool-use + thinking
- `--config` = inline TOML text, `--config-file` = file path (not interchangeable)
- `--quiet` = `--print --output-format text --final-message-only` (parseable single output)
- `stream-json` output format escapes newlines, breaking JSON extraction — use `--quiet` instead
- Moonshot API base URL: `https://api.moonshot.ai/v1` (not `.cn`)

## Testing Locally

No test suite. Validate changes by:

```bash
# Syntax-check Python scripts
python3 -m py_compile .github/cerberus/scripts/parse-review.py
python3 -m py_compile .github/cerberus/scripts/aggregate-verdict.py

# Shellcheck bash scripts
shellcheck .github/cerberus/scripts/run-reviewer.sh
shellcheck .github/cerberus/scripts/post-comment.sh

# Test parse-review against sample output
echo '...LLM output with ```json block```...' | python3 .github/cerberus/scripts/parse-review.py

# Test aggregate-verdict with verdict JSON files in a directory
python3 .github/cerberus/scripts/aggregate-verdict.py ./test-verdicts/
```

End-to-end testing requires pushing to a branch and opening a PR on a repo with `MOONSHOT_API_KEY` secret configured. Current test target: `misty-step/moonbridge` PR #80.

## GitHub Actions Gotchas

- `gh pr view --json comments` returns GraphQL node IDs — use `gh api repos/.../issues/N/comments` for REST numeric IDs
- `pull-requests: write` permission is required for posting PR comments
- Secrets are snapshotted per workflow run — push a new commit to pick up secret changes
- `set -e` in steps means any command failure stops the step; `run-reviewer.sh` uses `set +e` around kimi invocation deliberately

## Deployment

This repo is meant to be copied into a target repository's `.github/` directory. The workflow triggers on `pull_request` events. The only required secret is `MOONSHOT_API_KEY`.
