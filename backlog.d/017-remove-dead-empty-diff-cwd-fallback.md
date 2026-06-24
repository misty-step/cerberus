# Remove the dead empty-diff fallback workspace and its cwd plumbing

Priority: P3 · Status: pending · Estimate: S

## Goal
Delete the `fallback_empty_diff` workspace branch (and the `cwd`/`RunPolicy.cwd`/`--cwd` plumbing that exists only to feed it) so the review harness can never write `review-artifact.json` into a real checkout.

## Why
Backlog 016 moved emission to a file the agent writes inside `workspace.path()`. For a non-empty diff the workspace is always a private temp dir (worktree or `temp/packet`), but the `fallback_empty_diff` branch sets the workspace to the caller's real `cwd` (`RunWorkspace::prepare`, harness.rs). With file emission, that path would drop `review-artifact.json` into the real directory. It is unreachable today — `validate_request` rejects an empty diff in `review()` and `review_pr()` before the kernel runs — but it is a latent footgun for any library caller of `ReviewKernel::review` that skips validation, and the `cwd` plumbing (kernel `RunPolicy.cwd`, the `--cwd` CLI flag, the `fallback_cwd` param threaded through both substrate fns) now exists only to serve this dead branch.

## Non-Goals
- Do not change behavior for any reachable (non-empty-diff) request.
- Keep `--cwd` only if a real consumer needs it; otherwise delete it with the rest.

## Oracle
- [ ] The empty-diff case routes to a private temp dir (or is rejected outright), never the real cwd; a unit test calling the kernel directly with an empty diff proves no file lands outside a tempdir.
- [ ] `fallback_cwd` / `RunPolicy.cwd` / `--cwd` are removed if they have no other consumer (or a stated reason to keep each).
- [ ] `./scripts/verify.sh` green; no behavior change for diff-bearing requests.

## Notes
Surfaced by the 016 diverse-provider review (fresh-context critic, non-blocking). Fail-closed today, so this is hardening + a small deletion, not a bug fix.
