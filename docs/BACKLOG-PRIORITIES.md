# Backlog Priorities

This repo uses a two-tier priority model:

1. Primary: production-ready OSS Cerberus.
2. Deferred: research and expansion.

Everything else is deferred.

## Active Milestones

- `PRIMARY 1: OSS Production Readiness`
  - Reliability blockers.
  - Truthful CI/check semantics (no false-green).
  - Core security and failure-mode hardening.
  - Cross-reviewer recall hardening: Cerberus should not routinely miss issues other AI reviewers catch first.
  - Large-PR review reliability: reduce correctness/security timeouts and skip-driven blind spots.
- `PRIMARY 2: OSS Chargeability Hardening`
  - Coverage and quality-gate ratchet.
  - Maintainability and supportability work needed for paid usage.
  - Benchmark loop and scorecard ritual for recurring reviewer audits.
  - Prompt/context/agentic experiments driven by benchmark misses, not intuition.
- `DEFERRED: Research / Expansion`
  - Research spikes and long-horizon product expansion.

## Label Rules

- Strategic goal labels (required on all open issues):
  - `goal/primary-oss-prod`
  - `goal/deferred`
- Priority labels:
  - `p0` for production-break or merge-trust blockers.
  - `p1` for near-term essential hardening.
  - `p3` for deferred work.

## Benchmark-Driven Recall Program (`#331`)

- This section is the repo-local planning mirror for epic `#331`.
- Keep every benchmark-backed child lane here until `#331` closes so the issue body, scorecards, and repo docs do not drift.
- Latest benchmark evidence: `docs/reviewer-benchmark/2026-03-14-org-scorecard.md`

- `P1` Benchmark loop
  - Tracking: `#332`
  - Status: `child issue closed; keep mapped here until #331 closes`
  - Benchmark evidence: `docs/reviewer-benchmark/2026-03-08-org-scorecard.md`, `docs/reviewer-benchmark/2026-03-13-org-scorecard.md`, `docs/reviewer-benchmark/2026-03-14-org-scorecard.md`
  - Verification: `docs/reviewer-benchmark/README.md`, `tests/test_reviewer_benchmark_docs.py`, `tests/test_reviewer_benchmark_skill.py`
  - Weekly org-wide reviewer scorecard plus the durable repo-local benchmark skill.
- `P0` Security/dataflow blind-spot hardening
  - Tracking: `#333`
  - Status: `child issue closed; keep mapped here until #331 closes`
  - Benchmark evidence: `bitterblossom#495`, `cerberus-cloud#94`, `volume#417`
  - Verification: `tests/test_security_prompt_contract.py`, `tests/test_evals_config.py`
  - Untrusted-data re-entry checks now cover titles, branch names, fail-open defaults, raw error leakage, and async side effects.
- `P0` Large-PR timeout/blind-spot reduction
  - Tracking: `#334`
  - Status: `child issue closed; keep mapped here until #331 closes`
  - Benchmark evidence: `volume#401`, `volume#417`, `gitpulse#184`
  - Verification: `tests/test_review_slicing.py`, `tests/test_run_reviewer_runtime.py`, `docs/walkthroughs/issue-334-timeout-slice.md`
  - Correctness and security now use bounded high-risk slices before timeout salvage on large diffs.
- `P1` Lifecycle/state-machine challenger reasoning
  - Tracking: `#335`
  - Status: `child issue closed; keep mapped here until #331 closes`
  - Benchmark evidence: `bitterblossom#477`, `bitterblossom#509`
  - Verification: `tests/test_lifecycle_state_reasoning.py`, `tests/test_evals_config.py`
  - Force explicit phase-by-phase reasoning for sticky state, misclassified later handlers, and blocked-work retry loops.
- `P1` Adjacent-regression detection for workflow/infra changes
  - Tracking: `#336`
  - Status: `child issue closed; keep mapped here until #331 closes`
  - Benchmark evidence: `volume#407`, `volume#418`
  - Verification: `tests/test_adjacent_regression_guidance.py`, `evals/promptfooconfig.yaml`
  - Catch deleted workflows, weakened CI gates, and non-obvious neighboring-file regressions.
- `P1` Reviewer presence / self-dogfood coverage monitoring
  - Tracking: `#375`
  - Status: `child issue closed; keep mapped here until #331 closes`
  - Benchmark evidence: `docs/reviewer-benchmark/2026-03-13-org-scorecard.md`, `docs/reviewer-benchmark/2026-03-14-org-scorecard.md`
  - Verification: `defaults/dogfood.yml`, `scripts/check-dogfood-presence.py`, `tests/test_dogfood_presence.py`
  - Cerberus presence on core repos is tracked as benchmark health, not a footnote.
- `P1` Typed repo/GitHub context access for agentic review
  - Tracking: `#57`
  - Status: `child issue closed; keep mapped here until #331 closes`
  - Benchmark evidence: `cerberus#383`, `docs/reviewer-benchmark/2026-03-14-org-scorecard.md`
  - Verification: `tests/test_repo_read_contract.py`, `tests/test_github_read_contract.py`, `tests/test_github_read_integration.py`
  - Keep `repo_read` and `github_read` explicit, bounded, and safe enough to improve reviewer quality without widening the trust boundary.
- `P1` Prompt-contract simplification for tool-driven review
  - Tracking: `#381`
  - Status: `child issue closed; keep mapped here until #331 closes`
  - Benchmark evidence: `docs/reviewer-benchmark/2026-03-08-org-scorecard.md`, `docs/reviewer-benchmark/2026-03-13-org-scorecard.md`
  - Verification: `templates/review-prompt.md`, `tests/test_review_prompt_project_context.py`
  - The shared review prompt now centers on objective, tool posture, evidence bar, and trust boundaries instead of step-by-step procedure.
- `P1` Eval coverage for tool selection, grounding, and prompt-injection resistance
  - Tracking: `#380`
  - Status: `child issue closed; keep mapped here until #331 closes`
  - Benchmark evidence: `docs/reviewer-benchmark/2026-03-08-org-scorecard.md`, `docs/reviewer-benchmark/2026-03-13-org-scorecard.md`, `docs/reviewer-benchmark/2026-03-14-org-scorecard.md`
  - Verification: `tests/test_agentic_review_eval_contract.py`, `tests/test_evals_config.py`, `docs/walkthroughs/issue-380-agentic-review-evals.md`
  - Agentic-review eval fixtures now guard tool selection, linked-context grounding, adjacent-context evidence paths, and prompt-injection resistance.
- `P1` Terminology and contract alignment
  - Keep one canonical vocabulary for review objects in `docs/TERMINOLOGY.md`.
  - Avoid separate "verified" vs "unverified" finding types; findings stay first-class and are supported by evidence, citations, scope, and confidence.
  - Align prompts, docs, issues, walkthroughs, and PR language when terminology changes.
