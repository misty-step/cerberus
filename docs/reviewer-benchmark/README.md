# Reviewer Benchmark

Recurring cross-reviewer scorecards for Cerberus.

Purpose:
- Compare Cerberus against other AI reviewers on recent PRs.
- Identify unique Cerberus catches, Cerberus misses, and coverage gaps.
- Turn those findings into prompt, context, architecture, and model experiments.

Latest report:
- `2026-03-14-org-scorecard.md`
- `2026-03-13-org-scorecard.md`
- Prior report: `2026-03-08-org-scorecard.md`

Reusable workflow:
- Repo-local skill: `.agents/skills/reviewer-benchmark/SKILL.md`

Presence classification taxonomy:
- Every PR must be classified before drawing recall conclusions.
- Four buckets: `absent`, `skipped`, `present_clean`, `present_with_skips`.
- Only `present_clean` and `present_with_skips` produce genuine recall signal.
- `absent` is operational noise — no recall claim in either direction.
- `skipped` is partially operational (draft skips expected, key-missing skips are bugs).
- Core repos and minimum presence targets: `defaults/dogfood.yml`.
- Presence check: `python3 scripts/check-dogfood-presence.py`.

Collector contract:
- Output JSON includes top-level provenance: `org`, `since`, `repo_limit`, `pull_request_limit`, and `repo_listing_truncated`.
- Each repo entry lives under `repos.<name>` and includes `pull_requests`, `error`, and `truncated`.
- If `repo_listing_truncated` or any repo-level `truncated` flag is `true`, treat the scorecard as partial and rerun with higher limits before publishing conclusions.
