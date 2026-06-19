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

Tenth local retirement delivery, 2026-06-19:

- Added `cerberus-cli hosted-api-service-fixture --method ... --path ...` as
  the Rust-side service response fixture for the legacy hosted API contract.
- Kept the fixture offline and narrow: it renders health, auth rejection,
  queued POST creation, validation errors, GET status reads, not-found
  responses, and store error/unavailable bodies from explicit inputs without
  opening a socket, running a queue, cloning SQLite, calling GitHub, deploying,
  or executing reviewers.
- Added `HostedApiServiceStoreFixture` with checked fixtures for queued and
  completed reviews plus store-error and store-unavailable cases.
- Added adapter and CLI tests proving health bypasses auth, non-health routes
  require matching bearer auth, POST creation writes only safe dispatch pointer
  data, request tokens/API keys do not serialize, GET status returns the stored
  legacy run shape, and missing/non-integer IDs return `not_found`.
- Added dated QA evidence under
  `tmp/hosted-api-service-2026-06-19/` for health, missing auth, queued and
  completed status, queued POST, POST store error, and read-unavailable store.
- Updated API docs, architecture docs, docs index, and the retirement inventory
  to record service/status/auth/store-error fixture evidence while keeping
  `elixir-http-api` pending until Rust HTTP server wiring, real queue/store
  lifecycle, live GitHub acquisition, and deployment smoke exist.

Eleventh local retirement delivery, 2026-06-19:

- Added `cerberus-cli hosted-api-serve-fixture` as a bounded local Rust HTTP
  listener around the existing hosted API service fixture contract.
- Kept compatibility semantics in `cerberus-adapter`; the listener only binds
  an address, writes a ready file, parses minimal HTTP requests, returns JSON
  response bodies, and exits after `--max-requests`.
- Added CLI integration tests that spawn the server, make real TCP requests for
  health, missing auth, queued status, queued creation, and store-error
  creation, then assert the child process exits cleanly.
- Added dated QA evidence under
  `tmp/hosted-api-http-service-2026-06-19/` for health, missing auth, queued
  status, queued POST, and POST store error served over HTTP.
- Updated API docs, architecture docs, docs index, and the retirement inventory
  to record HTTP listener smoke evidence while keeping `elixir-http-api`
  pending until real queue/store lifecycle, live GitHub acquisition, reviewer
  execution, and deployment smoke exist.

Twelfth local retirement delivery, 2026-06-19:

- Added `--store-state <path>` to `cerberus-cli hosted-api-serve-fixture` so the
  bounded local Rust HTTP listener can persist POST-created queued reviews into
  a local `HostedApiServiceStoreFixture` JSON state file.
- Kept `--store <fixture>` read-only unless `--store-state` is explicitly
  provided; stateful mode resumes from an existing state file, otherwise seeds
  from `--store` or the default empty store.
- Kept queued review compatibility semantics in `cerberus-adapter` through
  `HostedApiServiceStoreFixture::record_queued_review`; the CLI server only
  wires loopback HTTP and file persistence.
- Added `hosted_api_fixture_server_persists_posted_reviews`, proving a real TCP
  `POST /api/reviews` returns a review id and a later
  `GET /api/reviews/:id` reads the persisted queued run shape.
- Added `hosted_api_fixture_server_maps_state_collision_to_store_error`,
  proving corrupted state that reuses the next review id returns structured
  `500 {"error":"store_error"}` instead of dropping the HTTP connection.
- Added dated QA evidence under
  `tmp/hosted-api-stateful-store-2026-06-19/`:
  `post-created.json`
  (`sha256:c07ee2f30445139ce946761a2d63a84cb44b639b81ca7ec53aaf85c1fd49f2e9`),
  `get-created.json`
  (`sha256:ca2e5511db233042fb609734d655f64b01bf237b23c3aab36fedf62049e4f628`),
  `store-state.json`
  (`sha256:bb6ec3702afc2fbbf8ef008cf2f3380a6eff5bb6040975e6f14ac9227692383b`),
  and `store-state-summary.json`
  (`sha256:3fb6647870fd98aee6e74b0cfff883131463fe7589f27fb1479a6dadd1b94e0f`).
- Token-leak grep over the QA packet found no `fixture-api-key`,
  `fixture-request-token`, or `github_token` material.
- Updated API docs, architecture docs, docs index, and the retirement inventory
  to record stateful local POST/GET store replay while keeping `elixir-http-api`
  pending until production queue/store lifecycle, live GitHub acquisition,
  reviewer execution, and deployment smoke exist.

Thirteenth local retirement delivery, 2026-06-19:

- Added `cerberus-cli hosted-api-worker-fixture` as the Rust-owned local worker
  lifecycle proof for a queued hosted review. It reads a mutable hosted API
  fixture store, reconstructs the dispatch request, combines explicit PR
  context plus diff into `ReviewRequest.v1`, runs `cerberus-core`, and writes a
  completed status containing the validated `ReviewRunArtifact.v1`.
- Kept the worker fixture narrow and offline: no live GitHub acquisition,
  production queue backend, deployment smoke, or provider-backed reviewer
  invocation happens in this slice.
- Added fail-closed coverage for PR-context head SHA mismatch; the command exits
  non-zero without writing worker outputs or mutating the store state.
- Added CLI integration coverage proving a completed worker status can be read
  back through the bounded Rust HTTP fixture server via `GET /api/reviews/77`.
- Added dated QA evidence under
  `tmp/hosted-api-worker-lifecycle-2026-06-19/`:
  `worker/review-request.json`
  (`sha256:625ffe45e91d5fdd0a28ba39401efdf5bd1dbd720b9389568fe4c384b800b9fe`),
  `worker/review-run-artifact.json`
  (`sha256:b68db9ac3853795254a3de482a8aaa30d5491e283412feb5728eb45cb849f981`),
  `worker/completed-status.json`
  (`sha256:0f0b0ef7f2eecf571505b9ffb8e36d526a6b7df2a7879e951282a81c5e49e1d0`),
  `store-state.json`
  (`sha256:ece95ceb3a926e84b7bbbba220be242c4cb07fd42c5cbe63cb04abff3ae6b0e1`),
  `get-completed.json`
  (`sha256:162bd1d3d3421b15ff2c7650c1fda1c122ed852a184dcf24bd230ae0533bc770`),
  and `get-completed-summary.json`
  (`sha256:a9001b48342e30b6bd06f59161e60ab4039fdb8f894252ff73b0091e795e8afd`).
- Token-leak grep over the QA packet found no `fixture-api-key`,
  `fixture-request-token`, or `github_token` material.
- Updated API docs, architecture docs, docs index, and the retirement inventory
  to record local worker completion while keeping `elixir-http-api` pending
  until production queue/store lifecycle, live GitHub acquisition,
  provider-backed reviewer execution, and deployment smoke exist.

Fourteenth local retirement delivery, 2026-06-19:

- Added typed `PeerHarnessCapabilities` to peer command profiles and execution
  plans so local repository reads and GitHub reads are explicit adapter
  authority boundaries before any peer harness is launched.
- Updated Pi, Goose, OpenCode, OMP, and fixture peer profiles to declare
  `local_repo_read: false` and `github_read: false`; the runner now copies
  those declarations into `PeerHarnessExecutionPlan.v3`.
- Updated rendered peer prompts to show the declared capabilities and forbid
  claims for any named source whose read capability is false.
- Added schema and runner coverage for fixture capabilities, generated plan
  capabilities, and prompt boundary text:
  `cargo test -p cerberus-schema peer_harness_command_profiles_declare_no_read_capabilities`,
  `cargo test -p cerberus-schema peer_harness_execution_plan_declares_read_capabilities`,
  `cargo test -p cerberus-cli peer_harness_runner_writes_execution_plan_without_live_provider_call`,
  `cargo test -p cerberus-cli peer_harness_runner_execution_plan_copies_mixed_read_capabilities`,
  `cargo test -p cerberus-cli peer_harness_runner_prompt_limits_mixed_read_capabilities`,
  and
  `cargo test -p cerberus-cli peer_harness_runner_writes_prompt_and_parses_transcript_artifact`.
- Added dated no-spend QA evidence under
  `tmp/peer-harness-read-capabilities-2026-06-19/`:
  `pi-plan.json`
  (`sha256:988cfa53a1801714be3ee3dde85a7bb619d50b1bf41b4fc3cd387c41fe95dbfa`),
  `pi-prompt.txt`
  (`sha256:0dec533fa70e101be45dc62b7b7283d3972fdc844afb35d13fa417de4ec4b909`),
  `pi-artifact.json`
  (`sha256:9bf536877ad8d6aa1b01b4e52c524632ca9e86d4420d0548fcef74a0aa77b902`),
  `pi-plan-summary.json`
  (`sha256:cc25564b9524ab292b6dd83ba115b5eff99daa1ea2887f8c03cff4cd15ed0f3f`),
  and `prompt-capability-lines.txt`
  (`sha256:99734317cac56c50644bad0ce5b4baac5c9e33f4269ab57f999569598a24899c`).
- Token-shaped secret grep over the QA packet found no `sk-`, `ghp_`, `ghs_`,
  `fixture-api-key`, or `fixture-request-token` material. The execution plan
  intentionally records required environment variable names, not values.
- Kept `elixir-review-tools` pending: this is a profile and prompt contract
  boundary for Cerberus-granted tool authority, not runtime sandboxing or an
  implementation of Rust local repo or GitHub read tools.

Fifteenth local retirement delivery, 2026-06-19:

- Decided the Rust cutover does not require a SQLite compatibility bridge for
  the legacy Elixir verdict store. The SQLite tables remain internal runtime
  state for review runs, per-reviewer verdicts, events, costs, and model
  performance queries, not the durable cross-harness evidence contract.
- Kept the Rust side on the existing deep interface:
  `ReviewRunArtifact.v1` plus `FileReviewRunArtifactStore` for immutable,
  schema-valid local, CI, Sprites, and hosted-dispatch receipts.
- Added `docs/shaping/005-verdict-store-sqlite-decision-plan.html` as the
  execution contract for the decision, including the falsifier that would
  reopen SQLite import work: a named consumer that needs to read historical
  Elixir database files.
- Updated the machine-checked and readable retirement inventories so the next
  `elixir-verdict-store` action is production Rust hosted queue/store
  lifecycle proof, not a SQLite port.
- Kept `elixir-verdict-store` pending and did not delete legacy files:
  production API persistence, deployment smoke, live GitHub acquisition, and
  provider-backed execution remain separate retirement gates.

Sixteenth local retirement delivery, 2026-06-19:

- Added `docs/walkthroughs/ARCHIVE.md` as the index for historical evidence
  roots before any future archive move: 34 historical files under
  `docs/walkthroughs/` excluding the new index, 16 under `artifacts/`, and 8
  under `walkthrough/`.
- Kept historical walkthroughs and artifacts in place. This slice does not
  delete, move, rewrite, or reclassify any old receipt as current architecture.
- Added `docs/shaping/005-historical-walkthrough-archive-index-plan.html` as
  the work contract for this retirement slice.
- Updated top-level docs and the docs index to route readers through the
  archive index when they need old evidence.
- Updated the retirement inventory so `historical-walkthroughs-and-artifacts`
  no longer has an open "create archive index" action; future movement must be
  a separate archive commit with rollback path preserved.
