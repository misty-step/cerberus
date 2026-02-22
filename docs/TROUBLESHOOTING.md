# Troubleshooting

## Fork PRs Don’t Run

Cerberus OSS runs inside GitHub Actions and needs a model API key secret.
GitHub does not expose repo secrets to fork PRs.

Fix:
- Keep the same-repo gate in your workflow:
  - `if: github.event.pull_request.head.repo.full_name == github.repository`

## All Reviewers SKIP

Common causes:
- API key missing/invalid
- Provider credits depleted / quota exceeded
- Timeouts on large diffs

What to check:
- Workflow logs: review step output for `API Error:` or `Review Timeout:`
- Verdict comment SKIP banner (credits depleted vs key invalid vs timeout)
- Artifacts: `cerberus-review-<perspective>` and `cerberus-verdict-<perspective>`

## No PR Comments / Inline Review

Cause: missing permissions for the job that posts.

Fix:
- Review jobs (per-perspective): `pull-requests: read` only
- Verdict job: `pull-requests: write`

## Override Command Doesn’t Work

Rules:
- SHA must match current PR HEAD: `/cerberus override sha=<sha>`
- Reason required
- Actor must satisfy policy in `defaults/config.yml` (and may be stricter for some reviewers)

## Triage Doesn’t Run / Runs Once

Triage loop guards:
- Skips commits with `[triage]` in commit message
- Caps attempts per PR+SHA (`max-attempts`)
- Scheduled triage requires `stale-hours` threshold

