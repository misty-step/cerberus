# Deliver closed-loop PR review output

Priority: P0 | Status: pending | Estimate: XL

## Goal

Let an operator run one Cerberus command for a pull request and get validated,
idempotent review output in GitHub while preserving the caller-neutral artifact.

## Oracle

- [ ] `cerberus review-pr --number <n> --repo <owner/name>` acquires the PR,
  runs the configured harness, writes request/artifact/markdown/execution
  receipts, and exits non-zero only for untrusted or failed review states.
- [ ] A dry-run mode shows the exact GitHub check/review/comment operations
  without writing to GitHub.
- [ ] A posting mode creates or updates a per-head-SHA Cerberus check summary
  and review comments without duplicating prior output.
- [ ] Inline comments map only to changed PR lines; unmappable comments fall
  back to contextual summary output.

## Verification System

- Claim: Cerberus can close the loop from GitHub PR context to useful GitHub
  review output without making GitHub the core product boundary.
- Falsifier: repeated runs duplicate comments; stale artifacts post to a new
  head SHA; inline anchors outside the diff are posted; dry-run output differs
  from real posting; a failed harness run posts a PASS check.
- Driver: local `cerberus review-pr --dry-run` fixture, integration tests with
  captured `gh api`/GitHub API fixtures, and one live self-review PR smoke when
  credentials are intentionally allowed.
- Grader: generated artifact validation, posting-plan snapshot, GitHub check
  state, and idempotency marker inspection.
- Evidence packet: `target/cerberus/review-pr/*`, GitHub PR URL, check-run URL,
  and posting transcript with token values redacted.
- Cadence: every change to request acquisition, rendering, posting, or artifact
  schema.

## Children

1. Add `review-pr` as orchestration over existing `request pr` and `review`.
2. Define a `PostPlan.v1` from `ReviewArtifact.v1` to GitHub check/review
   operations.
3. Implement dry-run rendering for checks, PR review body, inline comments, and
   contextual comments.
4. Implement idempotent GitHub posting with per-head-SHA markers and stale-run
   protection.
5. Add a live self-review smoke documented in README, gated behind explicit
   token allowlisting.

## Notes

**Why:** The product/operator lane found the largest usefulness gap: Cerberus
can generate artifacts, but normal operators still need manual glue to turn a
review artifact into GitHub feedback. GitHub docs distinguish PR review
comments and Checks annotations, with Checks annotations capped per request, so
posting needs a deliberate projection layer instead of a Markdown dump.
