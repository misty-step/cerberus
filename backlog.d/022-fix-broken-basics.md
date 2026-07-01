# Fix the broken basics before expanding Cerberus

Priority: P0 | Status: selected P0 slices shipped; residual safety/DX work remains | Estimate: M | Factory epic: 1

## Goal

Make the documented Cerberus path trustworthy before adding more orchestration:
the default production review path completes, releases cut cleanly, GitHub
projection has live proof, and the operator sees enough cost/time/context
evidence to decide whether a review is worth trusting.

## Oracle

- [x] The documented OpenCode/OpenRouter review path emits a valid
      `ReviewArtifact.v1` and `ReviewReceiptBundle.v1` for the small diff-only
      fixture without a `step_start`-only timeout.
- [x] Timeout failures name the harness/model/stage and point to the transcript
      or failed artifact path; silent hangs are not acceptable.
- [x] The next successful `master` Verify run triggers a green Release workflow
      and creates a GitHub release. The release path must not push generated
      changelog commits back to protected `master`.
- [x] GitHub projection is proven against a live sandbox PR or an equivalent
      wiremock contract for create/update/idempotence across summary, review,
      and inline-comment surfaces.
- [x] `review-pr --dry-run` either refuses ambient GitHub auth before any live
      read, or README and help text state that dry-run reads may use ambient
      `gh` auth while posting still refuses it.
- [ ] Existing safety and operator-visibility tickets that protect publication
      are complete enough that `./scripts/verify.sh` would catch likely
      execution and publication regressions.

## Children

1. **Done:** `021-glm52-artifact-timeout.md` moved to `_done/` after the live
   default GLM 5.2 path emitted a valid artifact and receipt in one initial
   attempt.
2. **Done:** release workflow fixed in PR #487. Live evidence on 2026-07-01:
   `master` Verify run `28551881723` triggered Release run `28551914709`, which
   created `v2.60.0`; the next GLM-fix merge also triggered green Release run
   `28552884422`.
3. Finish the publication-safety pieces from `008-pin-untested-safety-guards.md`
   and `009-operator-visibility-and-errors.md` that guard timeout/orphan kill,
   bounded output, request validation, cost/time/coverage rendering, CLI help,
   and actionable Checks 403 fallback guidance.
4. **Done:** `src/post.rs` has protocol-level proof in `./scripts/verify.sh`
   for check-run, summary, and inline-comment create/update/page-2 marker
   idempotence. Live proof on PR #489 used the fixture PASS artifact with
   `--summary-target status`: dry-run planned `create-commit-status` +
   `create-summary-comment`; first `--post` created status `49835544553` and
   summary comment `4860678694`; second `--post` created status `49835550120`
   and PATCHed the same summary comment. Evidence paths:
   `target/cerberus/live-post-pr-489/dry-run/post-plan.json`,
   `target/cerberus/live-post-pr-489/post-first/post-result.json`,
   `target/cerberus/live-post-pr-489/post-second/post-result.json`.
5. **Done:** dry-run now follows the same explicit-token rule as posting.
   `review-pr` resolves exactly one `--gh-token-file` or `--gh-token-env` before
   PR acquisition, stale-head checks, existing-state reads, or posting. The gate
   sets `GH_TOKEN=ambient-should-not-count` and verifies no fake-GitHub process
   runs when dry-run lacks an explicit token; explicit-token dry-run logs
   `AUTH gh_token=present github_token=absent` for PR reads and existing-state
   GETs.

## Notes

This is the first Factory priority because a review organ whose documented path
times out, whose release job is red, or whose projection path is dark cannot yet
be trusted as even an advisory PR workload.
