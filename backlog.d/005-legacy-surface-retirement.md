# 005 - Legacy Surface Retirement

Status: implemented-control-plane
Priority: P2
Type: epic
Created: 2026-06-18

## Goal

Retire or archive legacy Cerberus surfaces after the Rust engine proves parity
for the paths they currently support.

The objective is not a rewrite for its own sake. The objective is a smaller
repo whose public surface is Rust engine + adapter contracts, with legacy Elixir
and GitHub-only assumptions preserved only where they still buy compatibility.

## Oracle

For each legacy surface, a retirement table records:

- current responsibility
- Rust replacement or explicit reason to keep it
- parity fixture or caller test
- deletion/archive commit
- rollback path

No legacy engine module is deleted until its behavior is covered by Rust
fixtures or intentionally rejected as out of scope.

## Verification System

- Retirement table checked into `docs/shaping/`.
- `cargo test --workspace` covers replacement behavior.
- Legacy gates keep passing until the relevant surface is removed.
- Final retirement PR leaves `git status --short --untracked-files=all` clean
  and docs with no stale "Elixir engine is current" claims.

## Scope

In scope:

- `cerberus-elixir/` parity inventory.
- Root action/API compatibility decision.
- Node scaffolder compatibility decision.
- Old walkthrough/artifact cleanup or archive tags.
- AGENTS/docs source-of-truth updates as surfaces retire.

Out of scope:

- Deleting working compatibility before caller migration.
- Renaming public action refs without a migration plan.
- Keeping duplicate Elixir and Rust engines indefinitely.

## Evidence

- The repo already decommissioned the prior Python/Shell matrix pipeline.
- The current docs still name the Elixir engine as active, which will become
  stale as soon as Rust work lands.
- ADR 004 and the new backlog both point toward contracts as the durable seam.

## Child Work

1. Create the legacy responsibility inventory.
2. Mark each surface keep/port/delete/archive.
3. Add parity fixtures for kept behavior.
4. Delete or archive retired surfaces in small commits after parity.
5. Update README, docs, AGENTS, and templates after each retirement.

## Notes

This is intentionally sequenced after backlog 001 and 002. Premature deletion
would erase useful donor behavior before the Rust engine can prove it.

## Implementation Receipt

First local retirement delivery, 2026-06-18:

- Added `LegacySurfaceInventory.v1` and `LegacySurface` validation.
- Added `cerberus-cli validate-retirement <inventory.json>`.
- Added a checked JSON inventory plus readable table in `docs/shaping/`.
- Updated active docs to name Elixir as compatibility and point deletion work
  at the retirement inventory.
- Did not delete legacy code; all runtime surfaces remain until parity evidence
  and rollback metadata are recorded.

Second local retirement delivery, 2026-06-19:

- Added `cerberus-cli init-workflow` as the Rust-owned workflow-file scaffolder
  path for `templates/consumer-workflow-reusable.yml`.
- Added fixture tests for create, up-to-date, preserve-different, and report
  JSON behavior.
- Updated README, architecture docs, and the legacy surface inventory to record
  that Node remains pending for interactive API-key capture and live
  `gh secret set` compatibility.
- Did not delete `bin/cerberus.js`; `node-scaffolder` remains pending until the
  secret-setup half is ported or explicitly kept.

Third local retirement delivery, 2026-06-19:

- Added `cerberus-cli init` as the Rust-owned source-checkout setup command for
  workflow scaffolding plus noninteractive `gh secret set CERBERUS_API_KEY`.
- Added fake-`gh` tests proving the key is sent through stdin, reports stay
  redacted, the child `gh` process does not inherit `CERBERUS_API_KEY`, missing
  keys fail before workflow writes, `gh` errors are redacted, and workflow-only
  setup remains available through `cerberus-cli init-workflow`.
- Updated active docs and inventory to record that `bin/cerberus.js` remains
  only for npm packaging and hidden TTY prompt compatibility.
- Did not delete `bin/cerberus.js`; `node-scaffolder` remains pending until the
  package/prompt boundary is ported or explicitly kept.

Fourth local retirement delivery, 2026-06-19:

- Added Rust hidden-prompt parity for `cerberus-cli init` on interactive Unix
  TTYs when `CERBERUS_API_KEY` and `--api-key-stdin` are absent.
- Added raw-mode terminal echo restoration around the prompt, handled Ctrl-C
  and Ctrl-D without leaving echo disabled, and kept non-TTY no-key setup
  fail-closed before workflow writes.
- Proved the prompt path through PTY fake-`gh` QA: the terminal transcript does
  not contain the typed key, cancel restores terminal echo without writing a
  workflow, fake `gh` receives the key through stdin, and the child `gh`
  process still does not inherit `CERBERUS_API_KEY`.
- Updated active docs and inventory to record that `bin/cerberus.js` remains
  only for npm package compatibility.
- Did not delete `bin/cerberus.js`; `node-scaffolder` remains pending until npm
  package compatibility is ported or explicitly kept.

Fifth local retirement delivery, 2026-06-19:

- Deleted the unpublished npm scaffolder surface after
  `npm view @misty-step/cerberus version bin repository --json` returned E404
  from the public npm registry.
- Kept setup behavior in Rust: `cerberus-cli init` owns workflow scaffolding,
  hidden TTY prompting, stdin/env secret input, redacted reports, and
  `gh secret set CERBERUS_API_KEY`.
- Removed active `npx`, `node --check`, `bin/cerberus.js`, and package metadata
  references from the README, repo instructions, contributing docs, and default
  CI syntax gate.
- Added a Rust CI job for `cargo fmt --check`, `cargo test --workspace`, and
  retirement inventory validation so the merge gate covers the Rust surface
  that replaced the deleted Node check.
- Updated the retirement inventory to mark `node-scaffolder` covered by Rust
  fixture evidence.
- Recorded deletion commit `fba7271` in the machine-checked inventory in the
  follow-up receipt commit because a Git commit cannot name its own final hash.

Sixth local retirement delivery, 2026-06-19:

- Added `FileReviewRunArtifactStore` to the Rust adapter SDK so local, CI, and
  Sprites workflows can persist and replay immutable `ReviewRunArtifact.v1`
  receipts without adopting legacy SQLite semantics.
- Kept semantic replay validation in `cerberus-schema`: the store validates
  before writing, validates again after reading, rejects unsafe run IDs, and
  rejects artifacts loaded from the wrong run-id path or written over an
  existing receipt.
- Added focused adapter tests for valid round trip, malformed pre-persist
  artifacts, corrupt JSON, tampered persisted artifacts, unsafe run IDs, and
  run-id/path mismatch, and duplicate write rejection.
- Updated architecture and the retirement inventory to record partial
  `elixir-verdict-store` replacement evidence while keeping the surface pending
  until hosted/API persistence fixtures and any SQLite compatibility decision
  are complete.

Seventh local retirement delivery, 2026-06-19:

- Extended hosted API dispatch decisions with an optional validated
  `ReviewRunArtifact.v1` carried in completed poll responses as
  `review_run_artifact`.
- Added verdict consistency protection: a completed hosted response is invalid
  when the embedded artifact verdict disagrees with the top-level hosted
  verdict.
- Added request-head binding protection: a completed hosted response is invalid
  when the embedded artifact `reviewed_head_sha` does not match the hosted
  dispatch request `head_sha`.
- Added explicit Rust persistence wiring:
  `cerberus-cli github-action-dispatch` persists completed artifacts through
  `FileReviewRunArtifactStore` only when `CERBERUS_ARTIFACT_STORE` is set, and
  `hosted-api-dispatch-fixture` exposes the same path through
  `--artifact-store`.
- Kept parsed artifacts out of generic dispatch decision and recursively
  redacted verdict JSON serialization, so `--decision-out`, fixture `--out`,
  and `RUNNER_TEMP/cerberus-api-verdict.json` remain status transcripts rather
  than hidden artifact persistence paths.
- Added adapter and CLI fake-server coverage proving valid artifacts persist and
  replay, invalid artifacts fail closed, verdict mismatches fail closed, and an
  explicit store request fails if a completed hosted response omits the
  artifact or returns an artifact for the wrong head SHA.
- Updated API docs and the retirement inventory to record hosted/API
  persistence fixture evidence while keeping `elixir-verdict-store` pending
  until the SQLite compatibility decision is made.

Eighth local retirement delivery, 2026-06-19:

- Added a Rust hosted API ingress compatibility contract for legacy
  `POST /api/reviews` bodies. It preserves Elixir validation for `repo`,
  integer `pr_number`, `head_sha`, request-scoped `github_token`, optional
  `model`, and ignored unknown fields.
- Added `cerberus-cli hosted-api-ingress-fixture --body ... --out ...` so
  accepted and rejected POST bodies produce reviewable fixture reports without
  starting a server or fetching GitHub data.
- Kept token handling explicit: fixture reports expose only
  `github_token_present` and never serialize the raw request token.
- Fixed the Rust hosted dispatch adapter to accept the Elixir API's integer
  `review_id` response shape, while still rejecting unsafe string output
  values.
- Added checked fixtures under `fixtures/hosted-api/` plus adapter and CLI
  tests for valid requests, whitespace tokens, invalid header-breaking tokens,
  and missing required fields.
- Updated API docs, architecture docs, and the retirement inventory to record
  POST ingress parity while keeping `elixir-http-api` pending until Rust covers
  API auth/server wiring, GET status replay, storage/error mapping, deployment,
  and GitHub acquisition into `ReviewRequest.v1`.

Ninth local retirement delivery, 2026-06-19:

- Added the offline Rust hosted API acquisition bridge from a validated legacy
  POST body plus explicit PR context and raw diff into `ReviewRequest.v1`.
- Added `cerberus-cli hosted-api-request-fixture --body ... --pr-context ...
  --diff-file ... --out ...` as the runnable QA path for that bridge.
- Kept the bridge narrow: no live GitHub network call, HTTP server, queue,
  store lifecycle, deployment, provider execution, or model-selection behavior.
- Added head-SHA binding protection so acquired PR context must match the
  hosted POST `head_sha` before a core request is written.
- Added adapter and CLI tests proving happy-path request generation,
  malformed-ingress rejection, head-SHA mismatch rejection, malformed-diff
  rejection, stale-output removal, and request-token non-serialization.
- Updated API docs, architecture docs, and the retirement inventory to record
  acquisition evidence while keeping `elixir-http-api` pending until Rust
  covers API auth/server wiring, GET status replay, store error mapping, and
  deployment smoke.
