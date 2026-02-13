# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Cerberus is a multi-agent AI code review system shipped as a GitHub Action. Six parallel OpenCode CLI reviewers (powered by Kimi K2.5 via OpenRouter by default) each analyze a PR diff from a specialized perspective, then a council action aggregates their verdicts into a single merge-gating check.

## Architecture

```text
PR opened/synced
    │
    ▼
consumer workflow (.github/workflows/cerberus.yml)
    │
    ├── matrix job × N reviewers (parallel, fail-fast: false)
    │   └── uses: misty-step/cerberus@v2  (action.yml)
    │       ├── fetch PR diff/context
    │       ├── run-reviewer.sh   (prompt + opencode invocation)
    │       ├── parse-review.py   (extract + validate JSON verdict)
    │       ├── post-comment.sh   (optional per-reviewer PR comment)
    │       └── upload verdict artifact
    │
    └── verdict job (needs: review, if: always())
        └── uses: misty-step/cerberus/verdict@v2  (verdict/action.yml)
            ├── download verdict artifacts
            ├── aggregate-verdict.py  (override handling + council decision)
            └── post council comment + optional fail on FAIL

    └── triage job (optional, separate workflow/job)
        └── uses: misty-step/cerberus/triage@v2  (triage/action.yml)
            ├── read council verdict/comment state
            ├── enforce loop guards (`[triage]`, per-SHA attempt cap)
            ├── post diagnosis
            └── optional fix command + `[triage]` commit push
```

The consumer defines the reviewer matrix in its own workflow. This repository provides only the reusable actions and support files.

Inside the review action, `CERBERUS_ROOT` is set to `${{ github.action_path }}`. Scripts, agent configs, and templates are resolved relative to that root (`scripts/`, `.opencode/agents/`, `templates/`, `defaults/`).

### The Six Reviewers

| Name | Perspective | Shell Access | Focus |
|------|-------------|-------------|-------|
| APOLLO | correctness | no | Logic bugs, edge cases, type mismatches |
| ATHENA | architecture | no | Design patterns, module boundaries |
| SENTINEL | security | no | Threat model, injection, auth flaws |
| VULCAN | performance | no | Runtime efficiency, scalability |
| ARTEMIS | maintainability | no | DX, readability, future maintenance |
| CASSANDRA | testing | no | Test coverage gaps, regression risk |

Shell/bash access is denied per agent via `permission` in the agent markdown frontmatter.

### Key Files

- `action.yml` - review composite action entrypoint
- `verdict/action.yml` - council verdict composite action entrypoint
- `triage/action.yml` - triage composite action entrypoint
- `defaults/config.yml` - council settings, reviewer list, verdict thresholds, override rules
- `.opencode/agents/<perspective>.md` - OpenCode agent config (YAML frontmatter) + system prompt (body)
- `opencode.json` - OpenCode CLI config (provider, model, permissions)
- `templates/review-prompt.md` - user prompt template with `{{PLACEHOLDER}}` vars filled from PR context
- `templates/consumer-workflow.yml` - recommended workflow for downstream repositories
- `scripts/run-reviewer.sh` - orchestrates one reviewer: builds prompt, invokes `opencode run`
- `scripts/parse-review.py` - extracts last ` ```json ` block, validates required fields/types
- `scripts/post-comment.sh` - formats findings as markdown, upserts comment using HTML marker for idempotency
- `scripts/aggregate-verdict.py` - reads verdict JSON artifacts, applies override logic, writes council verdict
- `scripts/triage.py` - triage trigger router + circuit breaker + diagnosis/fix runtime

## Verdict Logic

Each reviewer emits: `FAIL` (any critical OR 2+ major) | `WARN` (1 major OR 5+ minor OR 3+ minor in same category) | `PASS`.
Only findings from reviews with confidence >= 0.7 count toward these thresholds.

Council: `FAIL` on a critical reviewer FAIL or 2+ reviewer FAILs (unless overridden) | `WARN` on any WARN or a single non-critical FAIL | `PASS` otherwise.

Override: `/council override sha=<sha>` comment on PR with reason. SHA must match HEAD. Actor constraints per `defaults/config.yml`.

## Output Schema

Every reviewer must end with a JSON block containing: `reviewer`, `perspective`, `verdict`, `confidence` (0-1), `summary`, `findings[]` (each with severity/category/file/line/title/description/suggestion), `stats` (files_reviewed, files_with_issues, critical, major, minor, info).

Optional finding fields:
- `evidence` (string) — exact code quote backing the claim (parser may downgrade unverified findings to `info`)
- `scope` (string) — set to `defaults-change` when citing unchanged code that became newly-defaulted

Optional fields added by the pipeline:
- `runtime_seconds` (int) — wall-clock seconds for the review, injected by action.yml after parsing.
- `raw_review` (string, max 50 KB) — preserved when JSON parsing fails but the model produced substantive text. Present in fallback/partial verdicts so the council comment can surface the raw analysis.

## OpenCode CLI

- Model: selected in `defaults/config.yml` (`reviewers[].model` or `model.default`), overridable via action input `model`
- Env vars: `OPENROUTER_API_KEY`
- Agent config: `.opencode/agents/<perspective>.md` (YAML frontmatter + system prompt body)
- CLI config: `opencode.json` at repo root (auto-discovered)
- Invocation: `opencode run -m <model> --agent <perspective> "<prompt>"`
- No TOML config, no agent YAML rewriting needed

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
- `set -e` in steps means any command failure stops the step; `run-reviewer.sh` uses `set +e` around opencode invocation deliberately

## Deployment

Consumers reference this repo as a GitHub Action. See `templates/consumer-workflow.yml` for the recommended setup. The only required secret is `OPENROUTER_API_KEY`.

Tagged releases follow semver. Consumers pin to `@v2` for automatic patch updates.
