# Cerberus

Multi-agent AI code review council for GitHub PRs.

Five specialized reviewers analyze every pull request in parallel, then a council verdict gates merge.

## Reviewers
| Name | Perspective | Focus |
|------|------------|-------|
| APOLLO | correctness | Logic bugs, edge cases, type mismatches |
| ATHENA | architecture | Design patterns, module boundaries, coupling |
| SENTINEL | security | Injection, auth flaws, data exposure |
| VULCAN | performance | Runtime efficiency, N+1 queries, scalability |
| ARTEMIS | maintainability | Readability, naming, future maintenance cost |

## Quick Start
1. Add one secret to your repository (Settings -> Secrets -> Actions):
   - Preferred: `CERBERUS_API_KEY`
   - Backward-compatible alias: `ANTHROPIC_API_KEY`

2. Create `.github/workflows/cerberus.yml`:

```yaml
name: Cerberus Council

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

concurrency:
  group: cerberus-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  review:
    name: "${{ matrix.reviewer }}"
    runs-on: ubuntu-latest
    strategy:
      matrix:
        include:
          - { reviewer: APOLLO, perspective: correctness }
          - { reviewer: ATHENA, perspective: architecture }
          - { reviewer: SENTINEL, perspective: security }
          - { reviewer: VULCAN, perspective: performance }
          - { reviewer: ARTEMIS, perspective: maintainability }
      fail-fast: false
    steps:
      - uses: actions/checkout@v4
      - uses: misty-step/cerberus@v1
        env:
          CERBERUS_API_KEY: ${{ secrets.CERBERUS_API_KEY || secrets.ANTHROPIC_API_KEY }}
        with:
          perspective: ${{ matrix.perspective }}
          github-token: ${{ secrets.GITHUB_TOKEN }}
          timeout: '120'

  verdict:
    name: "Council Verdict"
    needs: review
    if: always()
    runs-on: ubuntu-latest
    steps:
      - uses: misty-step/cerberus/verdict@v1
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
```

3. Open a pull request. That's it.

## How It Works
1. Each reviewer runs as a parallel matrix job
2. KimiCode CLI (Kimi K2.5) analyzes the PR diff from each perspective
3. Each reviewer posts a structured comment with findings
4. The verdict job aggregates all reviews into a council decision
5. Council verdict: **FAIL** on critical fail or 2+ fails, **WARN** on warnings or a single non-critical fail, **PASS** otherwise

## Auto-Triage (v1.1)
Cerberus ships a separate triage module for council failures:
- Action: `misty-step/cerberus/triage@v1`
- Modes: `off`, `diagnose`, `fix`
- Loop protection:
  - skips if head commit message contains `[triage]`
  - caps attempts per PR + SHA (`max-attempts`, default `1`)
  - trusts only bot-authored council/triage marker comments for gating
  - supports global kill switch: `CERBERUS_TRIAGE=off`

Use `templates/triage-workflow.yml` to enable:
- automatic triage on council `FAIL`
- manual triage via PR comment: `/cerberus triage` (optional `mode=fix`)
- scheduled triage for stale unresolved council failures

## Inputs
### Review Action (`misty-step/cerberus@v1`)
| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `perspective` | yes | - | Review perspective |
| `github-token` | yes | - | GitHub token for PR comments |
| `kimi-api-key` | no | - | Moonshot API key (optional if `CERBERUS_API_KEY` or `ANTHROPIC_API_KEY` env is set) |
| `kimi-base-url` | no | `https://api.moonshot.ai/v1` | API base URL |
| `model` | no | `kimi-k2.5` | Model name |
| `max-steps` | no | `25` | Max agentic steps |
| `timeout` | no | `120` | Review timeout in seconds (per reviewer job) |
| `kimi-cli-version` | no | `1.8.0` | KimiCode CLI version |
| `post-comment` | no | `true` | Post review comment |

### Verdict Action (`misty-step/cerberus/verdict@v1`)
| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `github-token` | yes | - | GitHub token for PR comments |
| `fail-on-verdict` | no | `true` | Exit 1 if council fails |

## Verdict Rules
Each reviewer emits:
- **FAIL**: any critical finding OR 2+ major findings
- **WARN**: exactly 1 major OR 5+ minor findings OR 3+ minor findings in the same category
- **PASS**: otherwise
- Only findings from reviews with confidence **>= 0.7** count toward verdict thresholds.

Council:
- **FAIL**: any critical reviewer FAIL OR 2+ reviewer FAILs (unless overridden)
- **WARN**: any reviewer WARN OR a single non-critical reviewer FAIL
- **PASS**: all reviewers pass

## Override Protocol
Comment on the PR:

```text
/council override sha=<short-sha>
Reason: <explanation>
```

The SHA must match the current HEAD commit. Override downgrades FAIL to non-blocking.

## Outputs
### Review Action
- `verdict`: PASS, WARN, or FAIL
- `verdict-json`: Path to the verdict JSON file

### Verdict Action
- `verdict`: Council verdict (PASS, WARN, FAIL)

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
- uses: misty-step/cerberus/verdict@v1
  with:
    github-token: ${{ secrets.GITHUB_TOKEN }}
    fail-on-verdict: 'false'
```

## Requirements
- GitHub repository with Actions enabled
- One secret: `CERBERUS_API_KEY` (or `ANTHROPIC_API_KEY` alias) with your Moonshot key (get one at [moonshot.ai](https://platform.moonshot.cn))
- `pull-requests: write` permission

## License
MIT
