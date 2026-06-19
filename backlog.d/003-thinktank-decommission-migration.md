# 003 - ThinkTank Decommission Migration

Status: implemented-cross-repo-docs
Priority: P1
Type: epic
Created: 2026-06-18

## Goal

Absorb the useful ThinkTank review-bench concepts into Cerberus, then retire
ThinkTank as a separate review-engine dependency.

ThinkTank can remain a general bench runner if it still has a reason to exist,
but Cerberus should not call ThinkTank to perform production review execution.

## Oracle

Cerberus owns equivalents for the ThinkTank review surfaces that matter:

- reviewer roster/config selection
- planner output or route plan
- per-reviewer artifacts
- coverage/degraded policy
- run manifest/cost metadata
- eval replay input for Daedalus

After migration, a Cerberus review fixture can be evaluated without invoking the
`thinktank` CLI, and docs identify ThinkTank as historical donor material for
review execution.

## Verification System

- Migration inventory: one checked-in table mapping ThinkTank artifacts to
  Cerberus schemas or explicit rejections.
- Fixture replay: a frozen ThinkTank review run is converted to
  `ReviewRunArtifact.v1` and validates under `cerberus-cli validate`.
- No runtime dependency: `rg -n "thinktank" crates/` returns only migration
  importer/export references unless a ticket explicitly permits another
  compatibility surface.

## Scope

In scope:

- Inventory ThinkTank `review/context.json`, `review/plan.json`,
  `review/coverage.json`, `review/degrade_policy.json`, `manifest.json`, and
  bench config.
- Port the concepts that deepen Cerberus's review engine.
- Write a decommission plan for any ThinkTank review-specific paths.

Out of scope:

- Deleting ThinkTank immediately.
- Importing ThinkTank's whole workflow model.
- Letting Cerberus shell out to ThinkTank for normal review execution.

## Evidence

- ThinkTank positions itself as a thin Pi bench launcher that owns launch,
  sandboxing, concurrency, timeouts, and artifacts.
- ThinkTank built-in config already has `review/default` with a planner,
  synthesizer, 10-agent roster, and review artifacts.
- The durable Cerberus module should own review semantics directly rather than
  wrapping another semantic engine.

## Child Work

- [x] Freeze one representative ThinkTank review run as migration input.
- [x] Write the artifact mapping table.
- [x] Add a one-way importer test for historical runs.
- [x] Port or reject each ThinkTank review surface explicitly.
- [x] Update ThinkTank docs/backlog after Cerberus can stand alone.

## Notes

This should run after backlog 001 establishes schemas and before production
callers depend on the new engine.

## Implementation Receipt

First local migration delivery, 2026-06-18:

- Added `docs/shaping/thinktank-migration-inventory.md`, mapping ThinkTank
  review context, route plan, manifest, reviewer artifacts, coverage/degrade
  policy, traces, prompts, auth homes, and CLI launch behavior to Cerberus
  schema destinations or explicit rejections.
- Added `fixtures/thinktank/review-pr-289/historical-run.json` as the compact
  frozen input and `fixtures/thinktank/review-pr-289/review-run-artifact.json`
  as the checked converted `ReviewRunArtifact.v1`.
- Added a one-way `cerberus-adapter` compatibility importer that validates the
  imported request, config, and artifact without invoking ThinkTank.
- Added a Rust guard keeping ThinkTank runtime references scoped to the
  compatibility importer.

Cross-repo documentation closeout, 2026-06-19:

- Added `docs/shaping/003-thinktank-cross-repo-doc-closeout-plan.html` as the
  plan and acceptance packet for the final docs/backlog migration slice.
- Updated ThinkTank `README.md` and `backlog.d/README.md` on branch
  `cerberus/003-decommission-docs` at commit `205914b` to state that ThinkTank
  review backlog work strengthens local bench/evidence and replay surfaces, not
  production Cerberus review execution.
- Reconfirmed the boundary in Cerberus: production review contracts are
  `ReviewRequest.v1`, `ReviewConfig.v1`, and `ReviewRunArtifact.v1`; ThinkTank
  remains donor material through frozen or exported artifacts only.
- Verified ThinkTank with `./scripts/with-colima.sh dagger call check`
  returning 13 passed / 0 failed on architecture, backlog, coveralls, dialyzer,
  e2e-smoke, elixir-quality, escript, gitleaks, harness-agents, models,
  security, shell, and yaml.
- Verified Cerberus with `cargo test --workspace thinktank_migration`,
  `cargo run --locked -p cerberus-cli -- validate
  fixtures/thinktank/review-pr-289/review-run-artifact.json`,
  `cargo test --workspace`, `cargo fmt --all -- --check`, legacy Elixir
  `mix test` / `mix format --check-formatted`, `node --check
  bin/cerberus.js`, shellcheck over actual checked-in shell scripts, and
  `git diff --check`.
- Audited runtime references with `rg -n "thinktank" crates/` and a broader
  runtime-invocation search over `crates`, `.github`, `action.yml`, `bin`,
  `defaults`, and `pi`; hits were limited to the compatibility importer,
  fixtures, and adapter exports.
- Fresh-context critic returned no blocking gaps; residual risk is future drift
  if a later change bypasses the importer guard or docs boundary.
