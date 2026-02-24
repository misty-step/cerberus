# Migrating from Cerberus v1 to v2

v2 is a breaking change. This guide covers everything you need to update.

---

## Why Upgrade

v1 is EOL — no further patches or features. v2 ships:

- **Smart routing** — an LLM router selects the most relevant reviewers per PR instead of running all six every time
- **Preflight gate** — detects forks, drafts, and missing API keys before spending tokens, with optional PR comment explaining the skip
- **Richer verdict** — inline PR comments anchored to diff lines, override support (`/cerberus override`), and skip/fail separation
- **Model diversity** — per-reviewer model assignment, a randomized pool, and a fallback chain for resilience
- **Reliability hardening** — empty-output retries, timeout fast-path fallback, staged OpenCode config, isolated HOME, parse-failure recovery

---

## What Changed

| Area | v1 | v2 |
|------|----|----|
| CLI runtime | KimiCode CLI | OpenCode CLI |
| Required secret | `MOONSHOT_API_KEY` | `OPENROUTER_API_KEY` |
| Action input | `kimi-api-key` | `api-key` |
| Skip-condition gate | `draft-check` | `preflight` (fork + draft + missing key) |
| Reviewer panel | Fixed 6 | Smart-routed, up to 8 available |
| Model | Single (Moonshot Kimi) | Pool + fallback chain (default: Kimi K2.5 via OpenRouter) |

---

## Step-by-Step Migration

### 1. Add the new secret

In your repository: **Settings → Secrets and variables → Actions → New repository secret**

- Name: `OPENROUTER_API_KEY`
- Value: get one at [openrouter.ai](https://openrouter.ai) (free tier available)

### 2. Replace your workflow

**Simplest path** — replace `.github/workflows/cerberus.yml` entirely:

```yaml
name: Cerberus

on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review, converted_to_draft]

concurrency:
  group: cerberus-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  review:
    uses: misty-step/cerberus/.github/workflows/cerberus.yml@v2
    permissions:
      contents: read
      pull-requests: write
    secrets:
      api-key: ${{ secrets.OPENROUTER_API_KEY }}
```

Or copy `templates/consumer-workflow-reusable.yml` from this repo.

**Power-user path** (full job control) — use `templates/consumer-workflow-minimal.yml`.

### 3. Update any explicit `api-key` inputs

If your v1 workflow passed `kimi-api-key` directly to a step, rename it:

```yaml
# before (v1)
with:
  kimi-api-key: ${{ secrets.MOONSHOT_API_KEY }}

# after (v2)
with:
  api-key: ${{ secrets.OPENROUTER_API_KEY }}
```

### 4. Test on a non-default branch first

Push to a branch and open a PR against it. Confirm the Cerberus jobs appear and complete before merging to your main branch.

### 5. Clean up v1 artifacts

- Remove the old `MOONSHOT_API_KEY` secret (Settings → Secrets → delete)
- Delete any `.kimicode/` config files if you had local overrides

---

## Common Issues

**Jobs are skipped with "missing API key"**
: The secret name changed. Ensure `OPENROUTER_API_KEY` is set (not `MOONSHOT_API_KEY`).

**`kimi-api-key` input not recognized**
: Rename to `api-key` in your workflow `with:` block.

**Fork PRs now get a PR comment instead of silently skipping**
: This is intentional — preflight posts an explanatory comment. Set `post-comment: 'false'` on the preflight step to suppress it.

---

## Getting Help

- [Troubleshooting guide](TROUBLESHOOTING.md)
- [Open an issue](https://github.com/misty-step/cerberus/issues)
