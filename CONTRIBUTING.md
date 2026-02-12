# Contributing to Cerberus

Thanks for improving Cerberus. This guide covers local development,
testing, release behavior, and consumer setup.

## Local Development

### Python and tool requirements

- Python: **3.12 recommended** (CI baseline), **3.10+ required**
  (scripts use `X | Y` type unions).
- Node.js: **22+** recommended (matches `action.yml`).
- Required CLIs for local script runs: `gh`, `jq`, and `timeout`.
  - On macOS, `timeout` comes from GNU coreutils.

Install `timeout` on macOS if needed:

```bash
brew install coreutils
```

### Setup

```bash
# from repo root
uv venv --python 3.12 --seed .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install pytest pyyaml
```

Install the same OpenCode CLI version used by the action:

```bash
npm i -g opencode-ai@1.1.49 --force
opencode --version
```

### Run review scripts locally

Perspectives currently supported by this repo:
`correctness`, `architecture`, `security`, `performance`, `maintainability`, `testing`.

Live run against a local diff:

```bash
# assumes the setup venv is already active

# 1) Build local PR-like inputs
# Use any diff file you want to review

git diff HEAD~1..HEAD > /tmp/pr.diff
cat > /tmp/pr-context.json <<'JSON'
{
  "title": "Local Cerberus test",
  "author": {"login": "local"},
  "headRefName": "local-branch",
  "baseRefName": "main",
  "body": ""
}
JSON

# 2) Run one reviewer
export CERBERUS_ROOT="$PWD"
export GH_DIFF_FILE=/tmp/pr.diff
export GH_PR_CONTEXT=/tmp/pr-context.json
export OPENROUTER_API_KEY="<your-openrouter-key>"
export REVIEW_TIMEOUT=600
export OPENCODE_MAX_STEPS=25
scripts/run-reviewer.sh security

# 3) Parse structured verdict JSON
python3 scripts/parse-review.py --reviewer SENTINEL \
  "$(cat /tmp/security-parse-input)" | jq .
```

Offline smoke test (no external API call):

````bash
source .venv/bin/activate
tmpbin="$(mktemp -d)"

# Stub timeout for environments that do not have GNU timeout installed.
cat > "$tmpbin/timeout" <<'SH'
#!/usr/bin/env bash
shift
exec "$@"
SH
chmod +x "$tmpbin/timeout"

# Stub opencode output with a valid reviewer JSON block.
cat > "$tmpbin/opencode" <<'SH'
#!/usr/bin/env bash
cat <<'OUT'
```json
{
  "reviewer": "STUB",
  "perspective": "security",
  "verdict": "PASS",
  "confidence": 0.95,
  "summary": "stub",
  "findings": [],
  "stats": {
    "files_reviewed": 1,
    "files_with_issues": 0,
    "critical": 0,
    "major": 0,
    "minor": 0,
    "info": 0
  }
}
```
OUT
SH
chmod +x "$tmpbin/opencode"

git diff HEAD~1..HEAD > /tmp/pr.diff
PATH="$tmpbin:$PATH" CERBERUS_ROOT="$PWD" GH_DIFF_FILE=/tmp/pr.diff \
  OPENROUTER_API_KEY=test-key REVIEW_TIMEOUT=5 OPENCODE_MAX_STEPS=5 \
  scripts/run-reviewer.sh security
python3 scripts/parse-review.py --reviewer SENTINEL \
  "$(cat /tmp/security-parse-input)" | jq -r '.verdict'
````

### Local test environment notes

- `scripts/run-reviewer.sh` requires `timeout` in `PATH`.
- Fast path and parser outputs are written under `/tmp/*-parse-input`,
  `/tmp/*-output.txt`, and `/tmp/*-verdict.json`.

## Testing

### Unit tests

```bash
source .venv/bin/activate

# all tests
python3 -m pytest tests/ -v

# or wrapper script
./tests/run-tests.sh
```

### Security tests (#56)

```bash
source .venv/bin/activate
python3 -m pytest tests/security/ -v
```

### Real PR dry-run (no PR comments posted)

This runs the reviewer pipeline against a real GitHub PR context,
but keeps results local.

```bash
source .venv/bin/activate
export GH_TOKEN="<github-token>"
export OPENROUTER_API_KEY="<your-openrouter-key>"

REPO="misty-step/cerberus"
PR="<pr-number>"

# Fetch real PR context

gh pr diff "$PR" --repo "$REPO" > /tmp/pr.diff
gh pr view "$PR" --repo "$REPO" \
  --json title,author,headRefName,baseRefName,body > /tmp/pr-context.json

# Run a reviewer locally (dry-run: no post-comment step)
export CERBERUS_ROOT="$PWD"
export GH_DIFF_FILE=/tmp/pr.diff
export GH_PR_CONTEXT=/tmp/pr-context.json
scripts/run-reviewer.sh correctness
python3 scripts/parse-review.py --reviewer APOLLO \
  "$(cat /tmp/correctness-parse-input)" > /tmp/correctness-verdict.json
jq -r '.verdict, .summary' /tmp/correctness-verdict.json
```

If you want a council-level result locally, generate multiple reviewer
verdict JSON files and run:

```bash
source .venv/bin/activate
python3 scripts/aggregate-verdict.py /path/to/verdicts
jq . /tmp/council-verdict.json
```

## Release Workflow

### Versioning model (`v1` vs `v2`)

- **Release tags** (`vX.Y.Z`) are created from `master` by the release pipeline.
- **Floating `v2` tag** is force-moved to the latest green
  default-branch commit by `.github/workflows/sync-v2-tag.yml`.
- **Floating `v1` tag** is force-moved to the latest matching `v1.x.x`
  release by `.github/workflows/sync-v1-tag.yml` via
  `scripts/sync-v1-tag.sh`.

### semantic-release configuration

semantic-release configuration lives in [`.releaserc.json`](.releaserc.json):

- `branches`: `master`
- plugins:
  - `@semantic-release/commit-analyzer`
  - `@semantic-release/release-notes-generator`
  - `@semantic-release/github`

Release execution is handled by
[`release.yml`](.github/workflows/release.yml), which runs
`misty-step/landfall@v1` and deletes any local `v2` tag before release
to avoid tag-fetch clobbering (issue #87).

### Triggering a release

Automatic:

- Push to `master` (typically merge a PR with Conventional Commit messages).

Manual (maintainers):

```bash
gh workflow run release.yml --repo misty-step/cerberus --ref master
gh run list --repo misty-step/cerberus --workflow release.yml --limit 5
```

Useful local inspection commands:

```bash
git fetch origin --tags --force
git tag -l 'v1.*' --sort=-v:refname | head -5
git rev-parse -q --verify refs/tags/v2
```

## Consumer Setup

### Add Cerberus workflow to another repository

Use the consumer template: [`templates/consumer-workflow.yml`](templates/consumer-workflow.yml)

```bash
mkdir -p .github/workflows
TEMPLATE_URL="https://raw.githubusercontent.com/misty-step/cerberus/v2/templates/consumer-workflow.yml"
curl -fsSL "$TEMPLATE_URL" -o .github/workflows/cerberus.yml
```

### Required secrets and permissions

Required secret:

- `OPENROUTER_API_KEY`

The workflow uses the default `GITHUB_TOKEN` automatically.

Required permissions (already modeled in the template):

- Review job: `contents: read`, `pull-requests: read`
- Verdict job: `contents: read`, `pull-requests: write`

### Configuration options

Review action options: [`action.yml`](action.yml)

- Required: `perspective`, `github-token`
- Common: `api-key`, `model`, `fallback-models`, `max-steps`,
  `timeout`, `post-comment`, `fail-on-skip`

Council verdict options: [`verdict/action.yml`](verdict/action.yml)

- `fail-on-verdict`
- `fail-on-skip`

Auto-triage options: [`triage/action.yml`](triage/action.yml)

- `mode` (`off`, `diagnose`, `fix`)
- `max-attempts`
- `stale-hours`
- `fix-command`

For auto-triage wiring, use [`templates/triage-workflow.yml`](templates/triage-workflow.yml).
