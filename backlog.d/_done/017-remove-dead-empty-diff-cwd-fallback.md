# Remove the dead empty-diff fallback workspace and its cwd plumbing

Priority: P3 · Status: done (2026-07-02) · Estimate: S

## Goal
Delete the `fallback_empty_diff` workspace branch (and the `cwd`/`RunPolicy.cwd`/`--cwd` plumbing that exists only to feed it) so the review harness can never write `review-artifact.json` into a real checkout.

## Why
Backlog 016 moved emission to a file the agent writes inside `workspace.path()`. For a non-empty diff the workspace is always a private temp dir (worktree or `temp/packet`), but the `fallback_empty_diff` branch sets the workspace to the caller's real `cwd` (`RunWorkspace::prepare`, harness.rs). With file emission, that path would drop `review-artifact.json` into the real directory. It is unreachable today — `validate_request` rejects an empty diff in `review()` and `review_pr()` before the kernel runs — but it is a latent footgun for any library caller of `ReviewKernel::review` that skips validation, and the `cwd` plumbing (kernel `RunPolicy.cwd`, the `--cwd` CLI flag, the `fallback_cwd` param threaded through both substrate fns) now exists only to serve this dead branch.

## Non-Goals
- Do not change behavior for any reachable (non-empty-diff) request.
- Keep `--cwd` only if a real consumer needs it; otherwise delete it with the rest.

## Oracle
- [x] The empty-diff case routes to a private temp dir, never the real cwd. `RunWorkspace::prepare` now always uses the `packet` tempdir it already creates for any diff-only request; the empty-diff case just gets a distinct `workspace_mode` label (`empty_diff_packet`) for observability. `harness::tests::empty_diff_request_still_resolves_to_a_private_tempdir_workspace` calls `RunWorkspace::prepare` directly with an empty diff and asserts the resolved path lives under the tempdir. Mutation-verified: temporarily made the empty-diff branch return `/tmp` directly, confirmed the test fails, restored.
- [x] `fallback_cwd` / `RunPolicy.cwd` / `--cwd` removed — no other consumer existed. Removed `fallback_cwd` param from `RunWorkspace::prepare`, `cwd` param from `run_fixture_substrate`/`run_command_substrate`, `RunPolicy.cwd` field, and the `--cwd` flag from `review`/`review-pr` (it had zero effect on real non-empty-diff behavior even before this change — `ExecutionPlan.cwd` was always `workspace.path()`, never the flag's value). Also renamed the now-accurately-named `with_packet` helper (was `with_packet_or_fallback`).
- [x] `./scripts/verify.sh` green; no behavior change for diff-bearing requests — confirmed, full suite + gate pass unchanged.

## Notes
Surfaced by the 016 diverse-provider review (fresh-context critic, non-blocking). Fail-closed today, so this is hardening + a small deletion, not a bug fix.
