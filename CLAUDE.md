# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Cerberus is a multi-agent AI code review system shipped as a GitHub Action. Six parallel Pi-runtime reviewers (powered by Kimi K2.5 via OpenRouter by default) each analyze a PR diff from a specialized perspective, then a verdict action aggregates their verdicts into a single merge-gating check.

Repo scope: this repository is the OSS BYOK GitHub Actions distribution. Cerberus Cloud (managed GitHub App) is planned as a separate repo/product (see `docs/adr/002-oss-core-and-cerberus-cloud.md`).

## Architecture

```text
PR opened/synced
    │
    ▼
consumer workflow (.github/workflows/cerberus.yml)
    │
    ├── preflight job (always runs first)
    │   └── uses: misty-step/cerberus/preflight@v2  (preflight/action.yml)
    │       ├── check: fork PR? → skip (no secrets available)
    │       ├── check: draft PR? → skip + optional PR comment
    │       ├── check: missing API key? → skip + optional PR comment
    │       └── outputs: should_run (bool), skip_reason (enum)
    │
    ├── matrix job × N reviewers (if: should_run, parallel, fail-fast: false)
    │   └── uses: misty-step/cerberus@v2  (action.yml)
    │       ├── fetch PR diff/context
    │       ├── run-reviewer.sh   (prompt + Pi runtime invocation)
    │       ├── parse-review.py   (extract + validate JSON verdict)
    │       ├── post-comment.sh   (optional per-reviewer PR comment)
    │       └── upload verdict artifact
    │
    ├── verdict job (needs: review, if: always() && should_run)
    │   └── uses: misty-step/cerberus/verdict@v2  (verdict/action.yml)
    │       ├── download verdict artifacts
    │       ├── aggregate-verdict.py  (override handling + verdict decision)
    │       ├── post verdict comment
    │       ├── post PR review w/ inline comments
    │       └── optional fail on FAIL
    │
    └── triage job (optional, separate workflow/job)
        └── uses: misty-step/cerberus/triage@v2  (triage/action.yml)
            ├── read verdict/comment state
            ├── enforce loop guards (`[triage]`, per-SHA attempt cap)
            ├── post diagnosis
            └── optional fix command + `[triage]` commit push
```

The consumer defines the reviewer matrix in its own workflow. This repository provides only the reusable actions and support files.

Inside the review action, `CERBERUS_ROOT` is set to `${{ github.action_path }}`. Scripts, agent configs, and templates are resolved relative to that root (`scripts/`, `.opencode/agents/`, `templates/`, `defaults/`).

### The Eight Reviewers

| Codename | Perspective | Focus |
|----------|-------------|-------|
| trace | correctness | Logic bugs, edge cases, type mismatches |
| atlas | architecture | Design patterns, module boundaries, coupling |
| guard | security | Threat model, injection, auth flaws |
| flux | performance | Runtime efficiency, scalability |
| craft | maintainability | DX, readability, future maintenance cost |
| proof | testing | Test coverage gaps, regression risk |
| fuse | resilience | Failure handling, retries, graceful degradation |
| pact | compatibility | Contract safety, version skew, rollback |

Shell/bash access is denied per agent via `permission` in the agent markdown frontmatter.

### Key Files

- `action.yml` - review composite action entrypoint
- `preflight/action.yml` - skip-condition gate (fork/draft/missing key) with PR comment support
- `verdict/action.yml` - verdict composite action entrypoint
- `triage/action.yml` - triage composite action entrypoint
- `validate/action.yml` - consumer workflow validator (misconfig guardrail)
- `defaults/config.yml` - verdict settings, reviewer list, verdict thresholds, override rules
- `.opencode/agents/<perspective>.md` - perspective system prompts (YAML frontmatter + body)
- `defaults/reviewer-profiles.yml` - Pi runtime profile settings (provider/model/tools/extensions/skills)
- `templates/review-prompt.md` - user prompt template with `{{PLACEHOLDER}}` vars filled from PR context
- `templates/consumer-workflow-reusable.yml` - recommended workflow for downstream repositories
- `templates/workflow-lint.yml` - optional workflow to catch YAML/syntax issues early
- `scripts/run-reviewer.sh` - orchestrates one reviewer via `scripts/run-reviewer.py` and Pi runtime
- `scripts/parse-review.py` - extracts last ` ```json ` block, validates required fields/types
- `scripts/post-comment.sh` - formats findings as markdown, upserts comment using HTML marker for idempotency
- `scripts/aggregate-verdict.py` - reads verdict JSON artifacts, applies override logic, writes aggregated verdict
- `scripts/post-verdict-review.py` - posts a single PR review with inline comments (best-effort) for verdict findings
- `scripts/triage.py` - triage trigger router + circuit breaker + diagnosis/fix runtime

## Verdict Logic

Each reviewer emits: `FAIL` (any critical OR 2+ major) | `WARN` (1 major OR 5+ minor OR 3+ minor in same category) | `PASS`.
Only findings from reviews with confidence >= 0.7 count toward these thresholds.

Cerberus verdict: `FAIL` on a critical reviewer FAIL or 2+ reviewer FAILs (unless overridden) | `WARN` on any WARN or a single non-critical FAIL | `PASS` otherwise.

Override: `/cerberus override sha=<sha>` comment on PR with reason. SHA must match HEAD. Actor constraints per `defaults/config.yml`.

## Output Schema

Every reviewer must end with a JSON block containing: `reviewer`, `perspective`, `verdict`, `confidence` (0-1), `summary`, `findings[]` (each with severity/category/file/line/title/description/suggestion), `stats` (files_reviewed, files_with_issues, critical, major, minor, info).

Optional finding fields:
- `evidence` (string) — exact code quote backing the claim (parser may downgrade unverified findings to `info`)
- `scope` (string) — set to `defaults-change` when citing unchanged code that became newly-defaulted
- `suggestion_verified` (boolean) — `true` if the suggestion was traced through the codebase and confirmed feasible; `false` if speculative (parser downgrades `false` findings to `info`)

Optional fields added by the pipeline:
- `runtime_seconds` (int) — wall-clock seconds for the review, injected by action.yml after parsing.
- `raw_review` (string, max 50 KB) — preserved when JSON parsing fails but the model produced substantive text. Stored in fallback/partial verdicts for debugging via workflow logs/artifacts (not rendered in PR comments).

## Pi Runtime

- Model: selected in `defaults/config.yml` (`reviewers[].model` or `model.default`), overridable via action input `model`. Set `model: pool` on a reviewer to randomly assign from `model.pool`/`model.tiers` each run.
- Env vars: `CERBERUS_OPENROUTER_API_KEY` (preferred), `OPENROUTER_API_KEY` (legacy)
- Perspective prompt: `.opencode/agents/<perspective>.md` (frontmatter ignored, body used as trusted system prompt)
- Runtime profile config: `defaults/reviewer-profiles.yml`
- Invocation path: `scripts/run-reviewer.sh` -> `scripts/run-reviewer.py` -> `scripts/lib/runtime_facade.py` (Pi CLI `--print` mode)
- Runtime executes in isolated HOME and emits telemetry to `${CERBERUS_TMP}/<perspective>-runtime-telemetry.ndjson`

## Testing Locally

```bash
# Run test suite
pip install pytest pytest-cov pyyaml
python3 -m pytest tests/ -v

# Or use the helper script
./tests/run-tests.sh

# Run with coverage
COVERAGE=1 ./tests/run-tests.sh
# Or directly:
python3 -m pytest tests/ --cov=scripts --cov-report=term-missing

# Lint
shellcheck scripts/*.sh
python3 -m py_compile scripts/parse-review.py
python3 -m py_compile scripts/aggregate-verdict.py
```

Coverage is enforced in CI at 70% (see `.coveragerc`). Configuration: `pytest.ini`, `.coveragerc`.

End-to-end testing requires pushing to a branch and having a target repo use `misty-step/cerberus@<branch>`. Current test target: `misty-step/moonbridge`.

## GitHub Actions Gotchas

- `gh pr view --json comments` returns GraphQL node IDs - use `gh api repos/.../issues/N/comments` for REST numeric IDs
- REST issue comment payloads expose actor as `user.login`; `author.login` is GraphQL-specific
- When testing workflow `--jq` snippets in YAML, assert key field usage (e.g. `.user.login`) without exact full-string matching to avoid whitespace-only test failures
- `pull-requests: write` permission is required for posting PR comments
- Secrets are snapshotted per workflow run - push a new commit to pick up secret changes
- `set -e` in steps means any command failure stops the step; review step uses `set +e` around `run-reviewer.sh` deliberately

## Deployment

Consumers reference this repo as a GitHub Action. See `templates/consumer-workflow-reusable.yml` for the recommended setup. The only required secret is `CERBERUS_OPENROUTER_API_KEY`.

Tagged releases follow semver. Consumers pin to `@v2` for automatic patch updates.
