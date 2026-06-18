# 003 - ThinkTank Decommission Migration

Status: shaped
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
- No runtime dependency: `rg "thinktank" crates/ src/` returns only migration
  docs/tests unless a ticket explicitly permits a compatibility importer.

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

1. Freeze one representative ThinkTank review run as migration input.
2. Write the artifact mapping table.
3. Add a one-way importer test for historical runs.
4. Port or reject each ThinkTank review surface explicitly.
5. Update ThinkTank docs/backlog after Cerberus can stand alone.

## Notes

This should run after backlog 001 establishes schemas and before production
callers depend on the new engine.
