# Deliver the operator-visibility VISION promises and actionable errors

Priority: P1 · Status: done (2026-07-02) · Estimate: M

## Goal
An operator reading Cerberus output sees the verdict, why each comment exists, what context was used/skipped, and the time/cost — and hits actionable messages on the predictable failures.

## Oracle
- [x] Rendered Markdown (and the GitHub summary/check, which reuse `render_markdown`) shows `run.duration_ms`, `run.cost_usd`, and `run.coverage` — `render.rs` now renders Duration/Cost lines and a Coverage section (files reviewed + files with findings) in production output, pinned by 5 new tests.
- [x] Every CLI flag has operator-facing `help` text — every `#[arg]` in `main.rs` (and every `Command`/`RequestCommand` subcommand) now carries a doc comment clap surfaces via `--help`.
- [x] A Checks-write `403` emits an actionable "retry with `--summary-target status`" message instead of a raw `gh` stderr dump — `GithubClient::api_raw` detects `check-runs` path + `403` and names the fix, pinned by a fake-gh-driven test.
- [x] `gh`/`git` spawn failure gives the same actionable not-found guidance as the harness-binary path — `request.rs::run_with_env` now distinguishes `ErrorKind::NotFound` and names the install-or-flag fix, pinned by a test.
- [x] `--dry-run` behavior is documented in help (it and `--post` are a mutually-exclusive ArgGroup; both flags now carry doc comments explaining the plan-only vs. publish behavior).

## Children
1. Render run cost/time/coverage (and "what was skipped") in the review Markdown. [direct VISION miss]
2. Add help text to every CLI flag.
3. Actionable Checks-write-denial → status-fallback message.
4. Consistent actionable `gh`-not-found message.
5. Honor or document `--dry-run`.

## Notes
**Why:** lane-dx F1-F5 (build clean; live CLI output captured; F1 lead-vetted — `render.rs` references `run`/`cost`/`coverage` only inside `#[cfg(test)]`). F1 is a direct miss on VISION's "operators can see what time/cost it took": the data is captured in the schema (`schema.rs:502-517`) but trapped in `artifact.json`. F4 is the highest-friction first-run moment — a classic-token operator hits a 403 that aborts with no hint to use the very fallback the docs prescribe. Credit: context *tiers* are already rendered (`render.rs:28-33`) and idempotent per-head-SHA markers are solid; the gap is cost/time/coverage + actionable errors.
