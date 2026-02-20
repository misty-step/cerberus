# Backlog Priorities

This repo now uses a strict two-tier priority model:

1. Primary: production-ready OSS Cerberus we can charge for.
2. Secondary: Cerberus Cloud SaaS bootstrap.

Everything else is deferred.

## Active Milestones

- `PRIMARY 1: OSS Production Readiness`
  - Reliability blockers.
  - Truthful CI/check semantics (no false-green).
  - Core security and failure-mode hardening.
- `PRIMARY 2: OSS Chargeability Hardening`
  - Coverage and quality-gate ratchet.
  - Maintainability and supportability work needed for paid usage.
- `SECONDARY: Cerberus Cloud Bootstrap (Separate Repo)`
  - Cloud setup and migration planning only.
  - Tracked by `#222`.
- `DEFERRED: Research / Expansion`
  - Research spikes and long-horizon product expansion.

## Label Rules

- Strategic goal labels (required on all open issues):
  - `goal/primary-oss-prod`
  - `goal/secondary-cloud-saas`
  - `goal/deferred`
- Priority labels:
  - `p0` for production-break or merge-trust blockers.
  - `p1` for near-term essential hardening.
  - `p2` for secondary Cloud work.
  - `p3` for deferred work.
- If Cloud work is intended to live in a separate repo, add:
  - `repo/cloud-split`

## Repo Boundary

This repository remains OSS core (review action, verdict, triage, schema contract, templates).

Cloud runtime concerns (GitHub App service, managed keys, quotas, billing, org controls) should move to a dedicated `cerberus-cloud` repository.

Tracking issue for split and migration: `#222`.
Cloud repo: `https://github.com/misty-step/cerberus-cloud`.
