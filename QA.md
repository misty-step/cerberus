# Cerberus QA Runbook

Cerberus is a multi-agent AI code review council for GitHub PRs, implemented as a GitHub Action. It runs 6 specialized reviewers in parallel and synthesizes a council verdict.

## Build & Test

Cerberus is distributed as a GitHub Action (not a standalone binary). There is no local build step.

### Integration Tests
```bash
# Run full test suite
python3 -m pytest tests/ -v

# Or via helper script
./tests/run-tests.sh

# Run individual test files
python3 -m pytest tests/test_aggregate_verdict.py -v
python3 -m pytest tests/test_run_reviewer_runtime.py -v
```

### Linting
```bash
# Shell scripts
shellcheck scripts/*.sh

# YAML validation
yamllint .
```

## Prerequisites

- GitHub repository with Actions enabled
- `OPENROUTER_API_KEY` secret (get at [openrouter.ai](https://openrouter.ai))
- Optional: `ANTHROPIC_AUTH_TOKEN` for Claude models
- GitHub CLI (`gh`) authenticated for testing

## Happy Path Testing

### 1. Basic Review (Consumer Workflow)
Create a test PR and verify the full council review:

1. Create a test repository or use an existing one
2. Add the `OPENROUTER_API_KEY` secret to the repo
3. Copy `templates/consumer-workflow.yml` to `.github/workflows/cerberus.yml`
4. Open a PR with meaningful code changes
5. Verify:
   - 6 reviewer jobs spawn (APOLLO, ATHENA, SENTINEL, VULCAN, ARTEMIS, CASSANDRA)
   - Each reviewer produces findings (PASS/WARN/FAIL/SKIP)
   - Verdict job runs after all reviews complete
   - Council verdict comment appears (FAIL/WARN/PASS)
   - Findings include file:line references

### 2. Reviewer Outputs
Each reviewer should produce:
- A structured PR comment with findings
- JSON verdict (PASS, WARN, FAIL, or SKIP)
- Findings tagged by severity (critical, major, minor)
- Timing information

### 3. Verdict Synthesis
The verdict job should:
- Aggregate all 6 reviewer verdicts
- Apply council rules:
  - FAIL: any critical FAIL OR 2+ FAILs
  - WARN: any WARN OR single non-critical FAIL
  - PASS: all reviewers pass
- Post a council summary comment with collapsible sections

### 4. Model Diversity
Test custom model assignment:
- Override `model` input per reviewer in matrix
- Verify different models are used
- Check `fallback-models` chain works on transient failures

### 5. Auto-Triage (v1.1)
Test the triage module:
- Enable via `templates/triage-workflow.yml`
- Modes: `diagnose`, `fix`, `off`
- Verify:
  - Auto-triage triggers on council FAIL
  - `/cerberus triage` comment works
  - Loop protection (max-attempts, `[triage]` skip)

## Edge Cases

### 1. PR with No Code Changes
- Documentation-only PRs
- Verify reviewers handle gracefully (should PASS with no findings)

### 2. Very Large PR (100+ files)
- Test timeout handling
- Verify `timeout` input (default 600s) is respected
- Check that review completes or times out cleanly

### 3. PR in Repo with No Cerberus Config
- Should fail gracefully with clear error message
- Fork PRs: skipped by the recommended consumer workflow (`if` gate); if the gate is removed, should fail with fork protection error

### 4. Model Provider Failure
- Test fallback chain: primary → fallback-models → SKIP
- Verify retry with exponential backoff (2s/4s/8s)
- Check `Retry-After` header is honored

### 5. Override Protocol
- Test `/council override sha=<short-sha>` comment
- Verify it downgrades FAIL to non-blocking

## Regression Checks

### SKIP Verdict Tracking
- When all reviews SKIP (timeout/API errors), council should emit SKIP verdict
- `fail-on-skip` input controls whether to fail the workflow

### Retry with Model Fallback
- Transient errors (429, 5xx, network) should trigger retry
- After exhausting retries, should try fallback models
- Final fallback should be SKIP verdict

### Consumer Workflow Matrix
- Verify all 6 reviewers are in the matrix
- Check that reviewer roster matches council composition
- Ensure `fail-fast: false` is set for parallel execution

### Fork Protection
- Verify fork PRs fail with clear security message
- Ensure secrets are not exposed to fork workflows

## Common Issues

| Issue | Likely Cause | Fix |
|-------|--------------|-----|
| All reviews SKIP | API key missing or invalid | Check `OPENROUTER_API_KEY` secret |
| Verdict never runs | Missing `needs: review` | Add dependency in workflow |
| No comments on PR | `comment-policy: 'never'` | Set to `non-pass` or `always` |
| Fork PR fails | Fork security | Use `if: github.event.pull_request.head.repo.full_name == github.repository` |

## Manual Testing Checklist

- [ ] Fresh repo with cerberus workflow triggers on PR
- [ ] All 6 reviewers spawn and complete
- [ ] Each reviewer produces findings (or clean pass)
- [ ] Verdict comment appears with summary
- [ ] Council verdict matches aggregated reviewer results
- [ ] Override comment downgrades FAIL
- [ ] Triage triggers on FAIL (if enabled)
- [ ] Large PR completes within timeout
- [ ] API failure triggers fallback chain
