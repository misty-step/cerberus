# Fix the broken basics before expanding Cerberus

Priority: P0 | Status: ready | Estimate: M | Factory epic: 1

## Goal

Make the documented Cerberus path trustworthy before adding more orchestration:
the default production review path completes, releases cut cleanly, GitHub
projection has live proof, and the operator sees enough cost/time/context
evidence to decide whether a review is worth trusting.

## Oracle

- [ ] The documented OpenCode/OpenRouter review path emits a valid
      `ReviewArtifact.v1` and `ReviewReceiptBundle.v1` for the small diff-only
      fixture without a `step_start`-only timeout.
- [ ] Timeout failures name the harness/model/stage and point to the transcript
      or failed artifact path; silent hangs are not acceptable.
- [ ] The next successful `master` Verify run triggers a green Release workflow
      and creates a GitHub release. The release path must not push generated
      changelog commits back to protected `master`.
- [ ] GitHub projection is proven against a live sandbox PR or an equivalent
      wiremock contract for create/update/idempotence across summary, review,
      and inline-comment surfaces.
- [ ] `review-pr --dry-run` either refuses ambient GitHub auth before any live
      read, or README and help text state that dry-run reads may use ambient
      `gh` auth while posting still refuses it.
- [ ] Existing safety and operator-visibility tickets that protect publication
      are complete enough that `./scripts/verify.sh` would catch likely
      execution and publication regressions.

## Children

1. **Done:** `021-glm52-artifact-timeout.md` moved to `_done/` after the live
   default GLM 5.2 path emitted a valid artifact and receipt in one initial
   attempt.
2. Fix the release workflow. Live evidence on 2026-07-01: Release run
   `28544516079` still failed because `@semantic-release/git` tried to push
   generated `CHANGELOG.md` back to protected `master`; `release.yml` already
   invokes Landmark, but `.releaserc.json` still carries the protected-branch
   write hazard.
3. Finish the publication-safety pieces from `008-pin-untested-safety-guards.md`
   and `009-operator-visibility-and-errors.md` that guard timeout/orphan kill,
   bounded output, request validation, cost/time/coverage rendering, CLI help,
   and actionable Checks 403 fallback guidance.
4. Add live or protocol-level proof for `src/post.rs` create/update/idempotence.
   The current repo gate exercises fake GitHub only; README documents the live
   smoke behind `CERBERUS_LIVE_REVIEW_PR=1`.
5. Decide and implement the `review-pr --dry-run` ambient-auth behavior. Posting
   safety shipped in `_done/014-post-as-cerberus-github-app.md`; dry-run still
   reads existing PR state before an explicit posting token is required.

## Notes

This is the first Factory priority because a review organ whose documented path
times out, whose release job is red, or whose projection path is dark cannot yet
be trusted as even an advisory PR workload.
