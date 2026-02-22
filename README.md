# Cerberus

Multi-agent AI code review for GitHub PRs.

Six specialized reviewers analyze every pull request in parallel, then Cerberus aggregates their verdicts into a single merge-gating check.

## Reviewers
| Role | Codename | Focus |
|------|----------|-------|
| Correctness & Logic | Apollo | Logic bugs, edge cases, type mismatches |
| Architecture & Design | Athena | Design patterns, module boundaries, coupling |
| Security & Threat Model | Sentinel | Injection, auth flaws, data exposure |
| Performance & Scalability | Vulcan | Runtime efficiency, N+1 queries, scalability |
| Maintainability & DX | Artemis | Readability, naming, future maintenance cost |
| Testing & Coverage | Cassandra | Test coverage gaps, regression risk |

## Quick Start
1. Add one secret to your repository (Settings -> Secrets -> Actions):
   - `OPENROUTER_API_KEY` — get one at [openrouter.ai](https://openrouter.ai)

2. Create `.github/workflows/cerberus.yml`:

```yaml
name: Cerberus

on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review, converted_to_draft]

concurrency:
  group: cerberus-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  draft-check:
    if: github.event.pull_request.head.repo.full_name == github.repository
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    outputs:
      is_draft: ${{ steps.draft.outputs.is_draft }}
    steps:
      - uses: misty-step/cerberus/draft-check@v2
        id: draft
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}

  validate:
    needs: draft-check
    if: github.event.pull_request.head.repo.full_name == github.repository && needs.draft-check.outputs.is_draft != 'true'
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: misty-step/cerberus/validate@v2

  matrix:
    needs: validate
    if: github.event.pull_request.head.repo.full_name == github.repository
    runs-on: ubuntu-latest
    outputs:
      matrix: ${{ steps.generate.outputs.matrix }}
    steps:
      - uses: misty-step/cerberus/matrix@v2
        id: generate

  review:
    needs: [matrix, draft-check]
    if: github.event.pull_request.head.repo.full_name == github.repository && needs.draft-check.outputs.is_draft != 'true'
    permissions:
      contents: read
      pull-requests: read
    name: "${{ matrix.reviewer_label || matrix.reviewer }}"
    runs-on: ubuntu-latest
    strategy:
      matrix: ${{ fromJson(needs.matrix.outputs.matrix) }}
      fail-fast: false
    steps:
      - uses: actions/checkout@v4
      - uses: misty-step/cerberus@v2
        with:
          perspective: ${{ matrix.perspective }}
          github-token: ${{ secrets.GITHUB_TOKEN }}
          api-key: ${{ secrets.OPENROUTER_API_KEY }}
          comment-policy: 'never'
          timeout: '600'

  verdict:
    name: "Cerberus Verdict"
    needs: [review, draft-check]
    if: always() && needs.review.result != 'skipped' && needs.draft-check.outputs.is_draft != 'true'
    permissions:
      contents: read
      pull-requests: write
    runs-on: ubuntu-latest
    steps:
      - uses: misty-step/cerberus/verdict@v2
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
```

Tip: copy `templates/consumer-workflow-minimal.yml` and `templates/workflow-lint.yml` (optional) instead of hand-editing YAML.

3. Open a pull request. That's it.

## Docs

- OSS vs Cloud: `docs/OSS-VS-CLOUD.md`
- Backlog priorities: `docs/BACKLOG-PRIORITIES.md`
- Troubleshooting: `docs/TROUBLESHOOTING.md`
- Architecture: `docs/ARCHITECTURE.md`
- Cloud repo: `https://github.com/misty-step/cerberus-cloud` (bootstrap)

## How It Works
1. Each reviewer runs as a parallel matrix job
2. OpenCode CLI analyzes the PR diff from each reviewer's perspective (default: Kimi K2.5 via OpenRouter, configurable per reviewer)
3. Reviewer runtime retries transient provider failures (429, 5xx, network) up to 3 times with 2s/4s/8s backoff and honors `Retry-After` when present
4. Each reviewer uploads a structured verdict artifact (optionally posts a per-reviewer PR comment)
5. The verdict job aggregates all reviews, posts a verdict comment, and posts a PR review with inline comments (up to 30) anchored to diff lines
6. Cerberus verdict: **FAIL** on critical fail or 2+ fails, **WARN** on warnings or a single non-critical fail, **PASS** otherwise

## Auto-Triage (v1.1)
Cerberus ships a separate triage module for verdict failures:
- Action: `misty-step/cerberus/triage@v2`
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
Full Cerberus review runs with full access to the `OPENROUTER_API_KEY` secret.

### Fork PRs
- Fork PRs trigger the workflow but skip the review jobs
- This is intentional: GitHub Actions secrets are **not available** to fork PRs
- Gate reviewer jobs to same-repo PRs (`head.repo.full_name == github.repository`) to avoid secret access attempts
- Full review requires a PR from the same repository (not a fork)

This prevents confusing failures when secret-dependent operations can't access their credentials.

## Inputs
### Review Action (`misty-step/cerberus@v2`)
| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `perspective` | yes | - | Review perspective |
| `github-token` | yes | - | GitHub token for PR comments |
| `api-key` | no | - | OpenRouter API key (optional if `CERBERUS_API_KEY` or `OPENROUTER_API_KEY` env is set) |
| `kimi-api-key` | no | - | Deprecated alias for `api-key` (OpenRouter API key) |
| `context` | no | `''` | Maintainer-provided project context injected into the reviewer prompt (do not include secrets) |
| `model` | no | `defaults/config.yml` | Model override (else per-reviewer config, then `model.default`) |
| `fallback-models` | no | `openrouter/google/gemini-3-flash-preview,...` | Comma-separated fallback models, tried on transient failure |
| `max-steps` | no | `25` | Max agentic steps |
| `timeout` | no | `600` | Review timeout in seconds (per reviewer job) |
| `opencode-version` | no | `1.1.49` | OpenCode CLI version |
| `comment-policy` | no | `never` | When to post comment: `never`, `non-pass` (WARN/FAIL), or `always` |
| `fail-on-skip` | no | `false` | Exit 1 if review verdict is SKIP (timeout/API error) |
| `fail-on-verdict` | no | `false` | Exit 1 if review verdict is FAIL |

### Verdict Action (`misty-step/cerberus/verdict@v2`)
| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `github-token` | yes | - | GitHub token for PR comments |
| `fail-on-verdict` | no | `true` | Exit 1 if Cerberus verdict is FAIL |
| `fail-on-skip` | no | `false` | Exit 1 if Cerberus verdict is SKIP (all reviews skipped) |

### Validate Action (`misty-step/cerberus/validate@v2`)
| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `workflow` | no | `.github/workflows/cerberus.yml` | Workflow file to validate |
| `fail-on-warnings` | no | `false` | Exit 1 if warnings are found |

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

## Outputs
### Review Action
- `verdict`: PASS, WARN, FAIL, or SKIP
- `verdict-json`: Path to the verdict JSON file

### Verdict Action
- `verdict`: Cerberus verdict (PASS, WARN, FAIL, SKIP)

## Customization
### Run fewer reviewers
Remove rows from the matrix:

```yaml
matrix:
  include:
    - { reviewer: APOLLO, perspective: correctness }
    - { reviewer: SENTINEL, perspective: security }
```

### Non-blocking reviews
```yaml
- uses: misty-step/cerberus/verdict@v2
  with:
    github-token: ${{ secrets.GITHUB_TOKEN }}
    fail-on-verdict: 'false'
```

### Model diversity
By default, Cerberus selects models per reviewer from `defaults/config.yml`.

Override per reviewer via the matrix `model` field (action input `model` overrides config). See `templates/consumer-workflow.yml` for a full example.

If you set `model`, Cerberus annotates the run with the configured model it would have used vs the override. Prefer leaving `model` unset to stay in sync with evolving per-reviewer defaults.

```yaml
matrix:
  include:
    - { reviewer: APOLLO,    perspective: correctness,     model: 'openrouter/moonshotai/kimi-k2.5' }
    - { reviewer: ATHENA,    perspective: architecture,    model: 'openrouter/z-ai/glm-5' }
    - { reviewer: SENTINEL,  perspective: security,        model: 'openrouter/minimax/minimax-m2.5' }
    - { reviewer: VULCAN,    perspective: performance,     model: 'openrouter/google/gemini-3-flash-preview' }
    - { reviewer: ARTEMIS,   perspective: maintainability, model: 'openrouter/moonshotai/kimi-k2.5' }
    - { reviewer: CASSANDRA, perspective: testing,         model: 'openrouter/google/gemini-3-flash-preview' }
```

If a reviewer's primary model fails with a transient error (429, 5xx, network), it retries with exponential backoff then falls through to the `fallback-models` chain before emitting SKIP.

### Fail when no review happened (SKIP)
```yaml
- uses: misty-step/cerberus/verdict@v2
  with:
    github-token: ${{ secrets.GITHUB_TOKEN }}
    fail-on-skip: 'true'
```

## Requirements
- GitHub repository with Actions enabled
- One secret: `OPENROUTER_API_KEY` (get one at [openrouter.ai](https://openrouter.ai))
- Permissions: `pull-requests: read` on review jobs, `pull-requests: write` on verdict job only

## License
Apache-2.0 (see [LICENSE](LICENSE))
