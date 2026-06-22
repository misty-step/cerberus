# Deliver the operator-visibility VISION promises and actionable errors

Priority: P1 · Status: pending · Estimate: M

## Goal
An operator reading Cerberus output sees the verdict, why each comment exists, what context was used/skipped, and the time/cost — and hits actionable messages on the predictable failures.

## Oracle
- [ ] Rendered Markdown (and the GitHub summary/check, which reuse `render_markdown` — `post.rs:335,397`) shows `run.duration_ms`, `run.cost_usd`, and `run.coverage`; today these are touched only in a `#[cfg(test)]` block (`render.rs:149+`) and the production render omits them.
- [ ] Every CLI flag has operator-facing `help` text (today all `#[arg]` in `main.rs:38-207` are blank — verified live via `--help`).
- [ ] A Checks-write `403` emits an actionable "retry with `--summary-target status`" message instead of a raw `gh` stderr dump (`post.rs:615-621`).
- [ ] `gh` spawn failure gives the same actionable not-found guidance as the harness-binary path (`harness.rs:845-850` is good; `request.rs:293-307` is a raw OS error today).
- [ ] `--dry-run` is either read explicitly or its no-op-but-safe default is documented in help (`main.rs:158,492`).

## Children
1. Render run cost/time/coverage (and "what was skipped") in the review Markdown. [direct VISION miss]
2. Add help text to every CLI flag.
3. Actionable Checks-write-denial → status-fallback message.
4. Consistent actionable `gh`-not-found message.
5. Honor or document `--dry-run`.

## Notes
**Why:** lane-dx F1-F5 (build clean; live CLI output captured; F1 lead-vetted — `render.rs` references `run`/`cost`/`coverage` only inside `#[cfg(test)]`). F1 is a direct miss on VISION's "operators can see what time/cost it took": the data is captured in the schema (`schema.rs:502-517`) but trapped in `artifact.json`. F4 is the highest-friction first-run moment — a classic-token operator hits a 403 that aborts with no hint to use the very fallback the docs prescribe. Credit: context *tiers* are already rendered (`render.rs:28-33`) and idempotent per-head-SHA markers are solid; the gap is cost/time/coverage + actionable errors.
