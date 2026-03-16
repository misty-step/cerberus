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

## Current Reviewer Hardening Tracks

- `P0` Security/dataflow blind-spot hardening
  - Tracking: `#333`
  - Benchmark evidence: `cerberus-cloud#94`, `volume#417`
  - Untrusted-data re-entry checks (titles, branch names, defaulted config, raw error leakage).
  - Fail-open / fail-closed review prompts for auth, quotas, env validation, and network isolation.
- `P0` Large-PR review reliability
  - Tracking: `#334`
  - Benchmark evidence: `gitpulse#184`, `volume#417`
  - Reduce `trace`/`guard` timeout rates on large diffs.
  - Split or re-slice review context before correctness/security lanes skip.
- `P1` Lifecycle/state-machine challenger lane
  - Tracking: `#335`
  - Benchmark evidence: `bitterblossom#477`, `bitterblossom#509` (from `2026-03-08-org-scorecard.md`; no bitterblossom PRs in March 13 window)
  - Force explicit phase-by-phase reasoning for sticky state, misclassified later handlers, and blocked-work retry loops.
- `P1` Adjacent-regression detection
  - Tracking: `#336`
  - Benchmark evidence: `volume#407`, `volume#418`
  - Catch deleted workflows, weakened CI gates, and non-obvious neighboring-file regressions.
- `P1` Benchmark loop
  - Tracking: `#332`
  - Benchmark evidence: `docs/reviewer-benchmark/2026-03-08-org-scorecard.md`, `docs/reviewer-benchmark/2026-03-13-org-scorecard.md`, `docs/reviewer-benchmark/2026-03-14-org-scorecard.md`
  - Weekly org-wide reviewer scorecard.
  - Durable agent-agnostic skill in `.agents/skills/reviewer-benchmark/`.
  - Hypothesis log plus experiment backlog tied to concrete misses.
- `P1` Reviewer presence / self-dogfood coverage
  - Tracking: `#375`
  - Benchmark evidence: `docs/reviewer-benchmark/2026-03-13-org-scorecard.md`, `docs/reviewer-benchmark/2026-03-14-org-scorecard.md`
  - Cerberus must run consistently enough on core repos for the benchmark to distinguish absence from recall failure.
  - Treat low Cerberus presence on `cerberus` and `gitpulse` as an operational reliability issue.
- `P1` Reviewer context retrieval
  - Tracking: `#57`
  - Benchmark evidence: `cerberus#383`, `docs/reviewer-benchmark/2026-03-14-org-scorecard.md`
  - Typed local and GitHub context retrieval must improve reviewer quality without weakening workspace/security boundaries.
  - Keep `repo_read` / `github_read` explicit and bounded.
  - Pull prior review comments, author fix summaries, and linked acceptance criteria into reviewer context by default.
- `P1` Terminology and contract alignment
  - Keep one canonical vocabulary for review objects in `docs/TERMINOLOGY.md`.
  - Avoid separate "verified" vs "unverified" finding types; findings stay first-class and are supported by evidence, citations, scope, and confidence.
  - Align prompts, docs, issues, walkthroughs, and PR language when terminology changes.
