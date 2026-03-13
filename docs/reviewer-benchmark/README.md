# Reviewer Benchmark

Recurring cross-reviewer scorecards for Cerberus.

Purpose:
- Compare Cerberus against other AI reviewers on recent PRs.
- Identify unique Cerberus catches, Cerberus misses, and coverage gaps.
- Turn those findings into prompt, context, architecture, and model experiments.

Latest report:
- `2026-03-13-org-scorecard.md`
- Prior report: `2026-03-08-org-scorecard.md`

Reusable workflow:
- Repo-local skill: `.agents/skills/reviewer-benchmark/SKILL.md`

Collector contract:
- Output JSON includes top-level provenance: `org`, `since`, `repo_limit`, `pull_request_limit`, and `repo_listing_truncated`.
- Each repo entry lives under `repos.<name>` and includes `pull_requests`, `error`, and `truncated`.
- If `repo_listing_truncated` or any repo-level `truncated` flag is `true`, treat the scorecard as partial and rerun with higher limits before publishing conclusions.
