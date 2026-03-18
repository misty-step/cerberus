# Cerberus

Multi-agent AI code review for GitHub PRs.

Cerberus ships a 6-reviewer bench and routes most PRs to a focused 4-reviewer panel instead of running the full bench every time.

## Quick Start (API Dispatch)

The fastest path: a single-step GHA action that dispatches to a hosted Cerberus instance.
Copy this into `.github/workflows/cerberus.yml`:

```yaml
name: Cerberus
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
permissions:
  contents: read
  issues: write
  pull-requests: write
jobs:
  review:
    if: github.event.pull_request.draft == false
    runs-on: ubuntu-latest
    steps:
      - uses: misty-step/cerberus/api@master
        with:
          api-key: ${{ secrets.CERBERUS_API_KEY }}
          cerberus-url: https://cerberus.fly.dev
```

Set one repository secret: `CERBERUS_API_KEY` (auth token for the Cerberus API).

The action dispatches a review via `POST /api/reviews`, polls until completion, and exits with the aggregated verdict. See [API contract](docs/api-contract.md) for the full HTTP reference.

<details>
<summary>API action inputs</summary>

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `api-key` | yes | - | Cerberus API authentication key |
| `cerberus-url` | yes | - | API base URL (e.g., `https://cerberus.fly.dev`) |
| `model` | no | `''` | Reserved; accepted but not yet wired to reviewer selection |
| `timeout` | no | `600` | Max seconds to wait for review completion |
| `poll-interval` | no | `5` | Seconds between status polls |
| `fail-on-verdict` | no | `true` | Exit 1 if aggregated verdict is FAIL |

</details>

## Quick Start (GHA Matrix — Legacy)

For teams that prefer running reviewers locally in GitHub Actions (BYOK model key):

```yaml
name: Cerberus
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review, converted_to_draft]
permissions:
  contents: read
  issues: write
  pull-requests: write
jobs:
  review:
    uses: misty-step/cerberus/.github/workflows/cerberus.yml@master
    secrets:
      api-key: ${{ secrets.CERBERUS_OPENROUTER_API_KEY }}
```

Then set one repository secret: `CERBERUS_OPENROUTER_API_KEY`.
Leave `with:` unset to run the default cost-controlled Cerberus configuration.

Prefer scaffolding? Run `npx @misty-step/cerberus init` to install the same reusable template and prompt for the secret.

## Smart Routing (Why 4 reviewers, not 6)
Cerberus routes each PR to the most relevant panel (default size: 4):

- `trace` (correctness) always runs
- `guard` (security) is required when non-doc/non-test code changes
- router is enabled by default in the reusable workflow

## Reviewers

| Codename | Perspective | Focus |
|----------|-------------|-------|
| trace | Correctness | Logic bugs, edge cases, type mismatches |
| guard | Security | Injection, auth flaws, data exposure |
| proof | Testing | Test coverage gaps, regression risk |
| atlas | Architecture | Design patterns, module boundaries, coupling |
| fuse | Resilience | Failure handling, retries, graceful degradation |
| craft | Maintainability | Readability, naming, future maintenance cost |

In API dispatch mode, the server-side router selects the panel and model tier in a single pass.

In GHA matrix mode, reviewers run in cascading waves with escalating model strength:

| Wave | Models | Reviewers | Question |
|------|--------|-----------|----------|
| wave1 | flash | trace · guard · proof | Does it work and is it safe? |
| wave2 | standard | atlas · fuse · craft | Is it well-designed? |
| wave3 | pro | trace · guard · atlas | Deep audit of highest stakes |

The gate between waves is a hard check: wave2 only runs when wave1 passes cleanly (no critical or major findings). Wave3 only runs when wave2 passes. This keeps cost proportional to signal.

## How It Works

**API dispatch mode:**
1. Thin GHA action sends `POST /api/reviews` with repo, PR number, and HEAD SHA
2. Server routes the PR to a focused reviewer panel (2-4 reviewers)
3. Reviewers run in parallel, supervised for fault tolerance
4. Verdict aggregation with finding dedup, then GitHub posting (verdict comment + inline PR review + check run)
5. Action polls `GET /api/reviews/:id` until `completed` or `failed`

See [`cerberus-elixir/README.md`](cerberus-elixir/README.md#pipeline) for the internal pipeline details.

**GHA matrix mode (legacy):**
1. Cerberus routes the PR to a focused reviewer subset, then runs that matrix in parallel
2. Pi CLI analyzes the PR diff from each reviewer's perspective (default: Kimi K2.5 via OpenRouter, configurable per reviewer)
   - Default reviewer tools omit shell execution; if `bash` is enabled for a profile, guardrails still block destructive and network-egress command patterns.
   - File-modifying tools are restricted to `/tmp` paths, and reviewer max-step caps are enforced at runtime.
3. Reviewer runtime retries transient provider failures (429, 5xx, network) up to 3 times with 2s/4s/8s backoff and honors `Retry-After` when present
4. Each reviewer uploads a structured verdict artifact (optionally posts a per-reviewer PR comment)
5. The verdict job aggregates all reviews, posts a verdict comment, and posts a PR review with inline comments (up to 30) anchored to diff lines
6. Cerberus verdict: **FAIL** on critical fail or 2+ fails, **WARN** on warnings or a single non-critical fail, **PASS** otherwise

## Docs

- **API contract**: [`docs/api-contract.md`](docs/api-contract.md)
- Migration guide (v1 → v2): `docs/MIGRATION.md`
- Review-run contract: `docs/review-run-contract.md`
- Terminology: `docs/TERMINOLOGY.md`
- Backlog priorities: `docs/BACKLOG-PRIORITIES.md`
- Troubleshooting: `docs/TROUBLESHOOTING.md`
- Architecture: `docs/ARCHITECTURE.md`

## Cost Snapshot

- API dispatch: single HTTP round-trip from GHA; all compute on the Cerberus server
- GHA matrix: three waves with flash → standard → pro model escalation, routing as the first cost-control gate
- Default model set: `kimi-k2.5`, `minimax-m2.5`, `glm-5`, `gemini-3-flash-preview`, `grok-4.1-fast`, `grok-4.20-beta`, `grok-4.20-multi-agent-beta`, `mercury-2`
- Practical monthly spend is typically below a single CodeRabbit seat for small/medium teams
- Exact spend depends on PR volume, diff size, and escalation rate

## Verdict Rules
Each reviewer emits:
- **FAIL**: any critical finding OR 2+ major findings
- **WARN**: exactly 1 major OR 5+ minor findings OR 3+ minor findings in the same category
- **PASS**: otherwise
- Only findings from reviews with confidence **>= 0.7** count toward verdict thresholds.

Cerberus verdict:
- **FAIL**: any critical reviewer FAIL OR 2+ reviewer FAILs (unless overridden)
- **WARN**: any reviewer WARN OR a single non-critical reviewer FAIL
- **PASS**: all reviewers pass

## Override Protocol
Comment on the PR:

```text
/cerberus override sha=<short-sha>
Reason: <explanation>
```

The SHA must match the current HEAD commit. Override downgrades FAIL to non-blocking.

## Auto-Triage (v1.1)
Cerberus ships a separate triage module for verdict failures:
- Action: `misty-step/cerberus/triage@master`
- Modes: `off`, `diagnose`, `fix`
- Loop protection:
  - skips if head commit message contains `[triage]`
  - caps attempts per PR + SHA (`max-attempts`, default `1`)
  - trusts only bot-authored verdict/triage marker comments for gating
  - supports global kill switch: `CERBERUS_TRIAGE=off`

Use `templates/triage-workflow.yml` to enable:
- automatic triage on Cerberus `FAIL`
- manual triage via PR comment: `/cerberus triage` (optional `mode=fix`)
- scheduled triage for stale unresolved verdict failures

## Fork PRs

Cerberus supports both same-repo and fork PRs with appropriate security handling:

### Same-Repo PRs
Full Cerberus review runs with full access to secrets.

### Fork PRs
- Fork PRs trigger the workflow but skip the review jobs
- This is intentional: GitHub Actions secrets are **not available** to fork PRs
- Gate reviewer jobs to same-repo PRs (`head.repo.full_name == github.repository`) to avoid secret access attempts
- Full review requires a PR from the same repository (not a fork)

This prevents confusing failures when secret-dependent operations can't access their credentials.

## Local Non-GHA Review Path

Cerberus ships one supported non-GitHub-Actions runner for maintainers and
future self-hosted orchestrators:

```bash
python3 scripts/non_gha_review_run.py \
  --repo misty-step/cerberus \
  --pr 329 \
  --output-dir /tmp/cerberus-review
```

Requirements:
- authenticated `gh`
- the same model API key env vars already used by `scripts/run-reviewer.py`

The command writes `pr.diff`, `pr-context.json`, `review-run.json`, per-reviewer
verdict JSON, and the final `verdict.json` into `--output-dir` while reusing the
existing runner, parser, and aggregator contracts.

<details>
<summary>GHA Matrix Mode — Full Inputs Reference</summary>

### Review Action (`misty-step/cerberus@master`)
| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `perspective` | yes | - | Review perspective |
| `github-token` | yes | - | GitHub token for PR comments |
| `api-key` | no | - | OpenRouter API key (optional if `CERBERUS_API_KEY`, `CERBERUS_OPENROUTER_API_KEY`, or `OPENROUTER_API_KEY` env is set) |
| `kimi-api-key` | no | - | Deprecated alias for `api-key` (OpenRouter API key) |
| `context` | no | `''` | Maintainer-provided project context injected into the reviewer prompt (do not include secrets) |
| `model` | no | `defaults/config.yml` | Model override (else per-reviewer config, then `model.default`) |
| `fallback-models` | no | `openrouter/google/gemini-3-flash-preview,...` | Comma-separated fallback models, tried on transient failure |
| `max-steps` | no | `25` | Max agentic steps |
| `timeout` | no | `600` | Review timeout in seconds (per reviewer job) |
| `pi-version` | no | `0.55.0` | Pi CLI version |
| `opencode-version` | no | `''` | Deprecated alias for `pi-version` (used only when `pi-version` is empty) |
| `comment-policy` | no | `never` | When to post comment: `never`, `non-pass` (WARN/FAIL), or `always` |
| `fail-on-skip` | no | `false` | Exit 1 if review verdict is SKIP (timeout/API error) |
| `fail-on-verdict` | no | `false` | Exit 1 if review verdict is FAIL |

### Verdict Action (`misty-step/cerberus/verdict@master`)
| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `github-token` | yes | - | GitHub token for PR comments |
| `fail-on-verdict` | no | `true` | Exit 1 if Cerberus verdict is FAIL |
| `fail-on-skip` | no | `false` | Exit 1 if Cerberus verdict is SKIP (all reviews skipped) |

### Validate Action (`misty-step/cerberus/validate@master`)
| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `workflow` | no | `.github/workflows/cerberus.yml` | Workflow file to validate |
| `fail-on-warnings` | no | `false` | Exit 1 if warnings are found |

### Outputs
**Review Action**: `verdict` (PASS, WARN, FAIL, SKIP), `verdict-json` (path to verdict JSON file)
**Verdict Action**: `verdict` (Cerberus verdict)

### Customization

**Run fewer reviewers:**
```yaml
matrix:
  include:
    - { reviewer: trace, perspective: correctness }
    - { reviewer: guard, perspective: security }
```

**Non-blocking reviews:**
```yaml
- uses: misty-step/cerberus/verdict@master
  with:
    github-token: ${{ secrets.GITHUB_TOKEN }}
    fail-on-verdict: 'false'
```

**Model diversity:**
By default, Cerberus selects models per reviewer from `defaults/config.yml`.

Cerberus runs cascading review waves:
- `wave1`: `grok-4.1-fast`, `mercury-2`, `minimax-m2.5`
- `wave2`: `kimi-k2.5`, `gemini-3-flash-preview`, `glm-5`
- `wave3`: `grok-4.20-beta`, `grok-4.20-multi-agent-beta`, `kimi-k2.5`

Override per reviewer via the matrix `model` field (action input `model` overrides config). See `templates/consumer-workflow-minimal.yml` for a full decomposed example.

**Fail when no review happened (SKIP):**
```yaml
- uses: misty-step/cerberus/verdict@master
  with:
    github-token: ${{ secrets.GITHUB_TOKEN }}
    fail-on-skip: 'true'
```

</details>

## Workflow Architecture
- **Primary (recommended):** API dispatch via `misty-step/cerberus/api@master`
- **GHA matrix (legacy):** reusable workflow via `misty-step/cerberus/.github/workflows/cerberus.yml@master`
- **Advanced / power user:** decomposed pipeline template at `templates/consumer-workflow-minimal.yml`
- **Optional:** add `templates/triage-workflow.yml` for automated failure triage

## Requirements
- GitHub repository with Actions enabled
- **API dispatch:** `CERBERUS_API_KEY` + hosted Cerberus URL
- **GHA matrix:** `CERBERUS_OPENROUTER_API_KEY` (get one at [openrouter.ai](https://openrouter.ai))
- Permissions: `pull-requests: read` on review jobs, `issues: write` on PR-thread comment jobs, and both `issues: write` plus `pull-requests: write` on verdict jobs

## License
Apache-2.0 (see [LICENSE](LICENSE))
