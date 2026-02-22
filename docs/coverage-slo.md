# Coverage SLOs — Tiered Module Targets

**Status**: Active  
**Last updated**: 2026-02-21  
**Related**: [#201 (ratchet policy)](https://github.com/misty-step/cerberus/issues/201), [#202](https://github.com/misty-step/cerberus/issues/202), [PR #230 (coverage-policy.yml)](https://github.com/misty-step/cerberus/pull/230)

---

## Motivation

A single global floor treats a security-critical JSON parser and a one-line entrypoint stub identically. This document defines per-tier SLOs so coverage effort is proportional to criticality, and so ratchet advances (tracked in `coverage-policy.yml`) can be staged realistically.

---

## Tier Definitions

| Tier | Label | Criteria |
|------|-------|----------|
| **1 — Critical** | `critical` | Verdict correctness, security boundaries, data parsing/aggregation. A regression here can cause false PASS verdicts, prompt injection, or data corruption. |
| **2 — Important** | `important` | Rendering, GitHub API interaction, override logic, config loading. Bugs cause visible failures or bad output, but not silent misbehavior. |
| **3 — Supporting** | `supporting` | CLI entrypoints, orchestration shims, format/utility helpers, non-critical tooling. Low complexity; failures are loud and recoverable. |

---

## Module Assignments

### Tier 1 — Critical

These modules are on the verdict correctness path or enforce security invariants.

| Module | Location | Rationale |
|--------|----------|-----------|
| `parse-review.py` | `scripts/parse-review.py` | Parses raw LLM output into verdict JSON; failure here silently corrupts all downstream decisions. |
| `aggregate-verdict.py` | `scripts/aggregate-verdict.py` | Aggregates multi-reviewer verdicts; applies override logic; determines final PASS/WARN/FAIL/SKIP. |
| `overrides.py` | `scripts/lib/overrides.py` | Override authorization and SHA validation; a bug here can allow unauthorized verdict flips. |
| `prompt_sanitize.py` | `scripts/lib/prompt_sanitize.py` | Sanitizes user-controlled PR data interpolated into prompts; prompt-injection defense. |
| `diff_positions.py` | `scripts/lib/diff_positions.py` | Maps findings to diff positions for inline PR comments; position errors cause silent mis-anchoring. |

**SLO targets — Tier 1:**

| Metric | Target | Current floor (`coverage-policy.yml`) |
|--------|--------|---------------------------------------|
| Line coverage | **90%** | 70% (global) |
| Branch coverage | **85%** | 70% (global, branch=true) |

---

### Tier 2 — Important

These modules produce user-visible output or mediate GitHub API calls. Bugs are noisy and correctness matters, but failures do not silently corrupt verdict data.

| Module | Location | Rationale |
|--------|----------|-----------|
| `post-verdict-review.py` | `scripts/post-verdict-review.py` | Posts PR review with inline comments; interacts with GitHub Reviews API; complex branching over findings. |
| `triage.py` | `scripts/triage.py` | Diagnoses failing verdicts and optionally triggers fix commits; circuit-breaker logic must not misfire. |
| `render_verdict_comment.py` | `scripts/lib/render_verdict_comment.py` | Renders the verdict PR comment; incorrect rendering causes confusing output but not wrong verdicts. |
| `render_findings.py` | `scripts/lib/render_findings.py` | Renders findings markdown; consumed by PR comments. |
| `findings.py` | `scripts/lib/findings.py` | Finding normalization, grouping, and reviewer-list formatting; feeds rendering pipeline. |
| `github.py` | `scripts/lib/github.py` | Idempotent comment upsert via HTML markers; used by all comment writers. |
| `github_reviews.py` | `scripts/lib/github_reviews.py` | PR review creation and listing; thin wrapper around GitHub API. |
| `defaults_config.py` | `scripts/lib/defaults_config.py` | Typed loader for `defaults/config.yml`; incorrect parsing propagates to all reviewer config consumers. |
| `consumer_workflow_validator.py` | `scripts/lib/consumer_workflow_validator.py` | Validates consumer workflow YAML; misconfig detection. |
| `collect-overrides.py` | `scripts/collect-overrides.py` | Collects override comments; feeds `aggregate-verdict.py`. |
| `generate-matrix.py` | `matrix/generate-matrix.py` | Parses config and emits reviewer matrix; wrong output silently drops reviewers from the bench. |

**SLO targets — Tier 2:**

| Metric | Target | Current floor |
|--------|--------|---------------|
| Line coverage | **80%** | 70% (global) |
| Branch coverage | **75%** | 70% (global) |

---

### Tier 3 — Supporting

Low-complexity entrypoints, tooling scripts, and infrastructure helpers. Failures are loud (exit codes, CI errors). These are covered adequately by integration paths in higher-tier tests.

| Module | Location | Rationale |
|--------|----------|-----------|
| `render-verdict-comment.py` | `scripts/render-verdict-comment.py` | One-line entrypoint shim delegating to `lib/render_verdict_comment.py`. |
| `render-findings.py` | `scripts/render-findings.py` | One-line entrypoint shim delegating to `lib/render_findings.py`. |
| `render-review-prompt.py` | `scripts/render-review-prompt.py` | Renders reviewer prompt template; used in CI, not verdict logic. |
| `read-defaults-config.py` | `scripts/read-defaults-config.py` | CLI wrapper around `defaults_config.py` for shell script consumption. |
| `validate-consumer-workflow.py` | `scripts/validate-consumer-workflow.py` | Entrypoint shim for `consumer_workflow_validator.py`. |
| `quality-report.py` | `scripts/quality-report.py` | Developer tooling; aggregates CI quality reports for human review. |
| `review_prompt.py` | `scripts/lib/review_prompt.py` | Prompt template rendering; no verdict logic. |
| `markdown.py` | `scripts/lib/markdown.py` | Markdown formatting helpers (badges, links, detail blocks). |
| `sitecustomize.py` | `scripts/sitecustomize.py` | Coverage hook for subprocesses; test infrastructure, not product logic. |

**SLO targets — Tier 3:**

| Metric | Target | Current floor |
|--------|--------|---------------|
| Line coverage | **70%** | 70% (global) |
| Branch coverage | **65%** | 70% (global) |

> Note: Tier 3 branch target is intentionally below the current global branch floor. These modules are expected to meet the global line floor by default; explicit branch tracking is low-value for shims and helpers.

---

## Summary Matrix

| Tier | Line target | Branch target | Modules |
|------|-------------|---------------|---------|
| 1 — Critical | 90% | 85% | `parse-review.py`, `aggregate-verdict.py`, `lib/overrides.py`, `lib/prompt_sanitize.py`, `lib/diff_positions.py` |
| 2 — Important | 80% | 75% | `post-verdict-review.py`, `triage.py`, `lib/render_verdict_comment.py`, `lib/render_findings.py`, `lib/findings.py`, `lib/github.py`, `lib/github_reviews.py`, `lib/defaults_config.py`, `lib/consumer_workflow_validator.py`, `collect-overrides.py`, `matrix/generate-matrix.py` |
| 3 — Supporting | 70% | 65% | `render-verdict-comment.py`, `render-findings.py`, `render-review-prompt.py`, `read-defaults-config.py`, `validate-consumer-workflow.py`, `quality-report.py`, `lib/review_prompt.py`, `lib/markdown.py`, `sitecustomize.py` |

---

## Migration Plan

This plan aligns with the ratchet schedule in `coverage-policy.yml` (PR #230).

### Phase 0 — Baseline (current, global floor: 70%)

- Document this SLO matrix (this file).
- Identify any Tier 1 modules below 90% line / 85% branch via `pytest --cov --cov-report=term-missing`.
- Open follow-up issues for each Tier 1 module below target.

### Phase 1 — Ratchet to 80% global (next step per `coverage-policy.yml`)

- All modules must reach the global 80% line floor.
- Tier 1 modules must reach 90% line / 85% branch.
- Tier 2 modules must reach 80% line / 75% branch.
- Suggested sequence: harden `overrides.py` and `diff_positions.py` first (highest risk, often undertested utility logic).

### Phase 2 — Tier 2 lock-in

- Once global floor hits 80%, add per-module enforcement in CI for Tier 1 and Tier 2.
- Mechanism: `coverage report --include=scripts/parse-review.py --fail-under=90` in a dedicated CI step (or a small enforcement script reading this SLO matrix).
- Tier 3 remains covered only by the global floor.

### Phase 3 — Full enforcement

- Per-tier enforcement is active in CI.
- New modules must declare their tier in a comment header or a `coverage-slo.yml` registry (TBD in a follow-up issue).
- Regressions in Tier 1 modules block merge regardless of global floor.

---

## Measurement

Run today's per-module coverage with:

```bash
python3 -m pytest tests/ \
  --cov=scripts \
  --cov-report=term-missing \
  --cov-report=json:coverage.json \
  -q

# Then inspect per-file line/branch numbers:
python3 -c "
import json
data = json.load(open('coverage.json'))
for f, d in sorted(data['files'].items()):
    s = d['summary']
    print(f'{f:60s}  line={s[\"percent_covered\"]:.0f}%  branch={s.get(\"percent_covered_branch\",0):.0f}%')
"
```

---

## Governance

- This document is the source of truth for tier assignments.
- Tier reassignments require a PR with rationale.
- Coverage targets may only increase (never decrease) once a tier reaches its SLO.
- The ratchet schedule lives in `coverage-policy.yml`; this file describes per-module targets that layer on top of it.
