# Contributing to Cerberus

Thanks for contributing to Cerberus.

This guide covers local development, testing, release behavior, and consumer setup.

## Local Development

### Python Version

Cerberus CI runs on Python 3.12 (`.github/workflows/ci.yml`), and the
scripts use modern type syntax.
Use Python 3.12+ locally.

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
python --version
uv pip install pytest pyyaml
```

### Local Repo Validation

These checks mirror lightweight parts of CI:

```bash
python -m py_compile \
  scripts/parse-review.py \
  scripts/aggregate-verdict.py \
  scripts/triage.py
```

```bash
python - <<'PY'
import yaml
for path in [
    "action.yml",
    "verdict/action.yml",
    "triage/action.yml",
    "templates/triage-workflow.yml",
]:
    with open(path, encoding="utf-8") as f:
        yaml.safe_load(f)
    print(f"{path}: valid")
PY
```

### Run Review Pipeline Scripts Locally

Parse a sample reviewer output:

```bash
python scripts/parse-review.py tests/fixtures/sample-output-pass.txt > /tmp/correctness-verdict.json
```

Aggregate sample reviewer verdicts:

```bash
mkdir -p /tmp/cerberus-docs-verdicts
cp tests/fixtures/sample-verdicts/*.json /tmp/cerberus-docs-verdicts/
python scripts/aggregate-verdict.py /tmp/cerberus-docs-verdicts
```

Render a council comment from the aggregated verdict:

```bash
python scripts/render-council-comment.py \
  --council-json /tmp/council-verdict.json \
  --output /tmp/council-comment.md
```

Run one real reviewer locally (requires credentials and OpenCode CLI):

```bash
export CERBERUS_ROOT="$PWD"
export OPENROUTER_API_KEY="<your-openrouter-api-key>"
export GH_TOKEN="$(gh auth token)"
gh pr diff <pr-number> > /tmp/pr.diff
gh pr view <pr-number> --json title,author,headRefName,baseRefName,body > /tmp/pr-context.json
export GH_DIFF_FILE=/tmp/pr.diff
export GH_PR_CONTEXT=/tmp/pr-context.json
export OPENCODE_MODEL="openrouter/moonshotai/kimi-k2.5"
export OPENCODE_MAX_STEPS=1
export REVIEW_TIMEOUT=60
scripts/run-reviewer.sh security
python scripts/parse-review.py /tmp/security-output.txt > /tmp/security-verdict.json
```

## Testing

### Unit Tests

Run all tests:

```bash
tests/run-tests.sh
```

or:

```bash
python -m pytest tests/ -v
```

### Coverage

CI enforces a minimum coverage threshold (see `.coveragerc`). Run locally:

```bash
COVERAGE=1 ./tests/run-tests.sh
```

### Security Regression Tests (#56)

```bash
python -m pytest tests/security/ -v
```

### Real PR Dry-Run Mode

Use the consumer workflow template and keep reviewer comments disabled:

- Start from [`templates/consumer-workflow.yml`](templates/consumer-workflow.yml).
- Keep `post-comment: 'false'` in the review job.
- Optionally set `fail-on-verdict: 'false'` in the verdict step while testing.
- Open a same-repo PR (fork PRs are intentionally blocked by the action).

## Release Workflow Notes

### Versioning Model (`v1` vs `v2`)

- Semantic release metadata is in [`.releaserc.json`](.releaserc.json).
- [`.github/workflows/release.yml`](.github/workflows/release.yml)
  runs release automation on pushes to `master` and on manual dispatch.
- [`.github/workflows/sync-v2-tag.yml`](.github/workflows/sync-v2-tag.yml)
  force-moves floating `v2` to the latest green default-branch commit.
- [`.github/workflows/sync-v1-tag.yml`](.github/workflows/sync-v1-tag.yml)
  runs [`scripts/sync-v1-tag.sh`](scripts/sync-v1-tag.sh) to move floating
  `v1` to the latest `v1.x.x` tag.

Inspect tag state locally:

```bash
git fetch origin --tags --force
git tag -l 'v1*' | sort -V
git tag -l 'v2*' | sort -V
git rev-parse --verify refs/tags/v1^{commit}
git rev-parse --verify refs/tags/v2^{commit}
```

### Triggering a Release

- Automatic: merge to `master`.
- Manual: run the **Release** workflow
  (`.github/workflows/release.yml`) via GitHub Actions UI
  (`workflow_dispatch`).

## Consumer Setup

### Add Cerberus to Another Repository

Use [`templates/consumer-workflow.yml`](templates/consumer-workflow.yml)
as the baseline workflow:

- Review jobs must have read-only permissions.
- Verdict job is the only job that needs `pull-requests: write`.

### Required Secrets and Permissions

- `OPENROUTER_API_KEY` secret in the consumer repository.
- `GITHUB_TOKEN` is provided by GitHub Actions.
- Use the least-privilege permissions split shown in the template.

### Configuration Options

Primary references:

- Review action inputs: [`action.yml`](action.yml)
- Verdict action inputs: [`verdict/action.yml`](verdict/action.yml)
- Triage action inputs: [`triage/action.yml`](triage/action.yml)
- Default policy/config: [`defaults/config.yml`](defaults/config.yml)
