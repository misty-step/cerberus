# 002 - Independent Caller Adapters

Status: done
Priority: P1
Type: epic
Created: 2026-06-18

## Goal

Make Bitterblossom and Olympus consume Cerberus through the same request/artifact
contract while remaining independent sibling callers. Neither system should
import, reference, configure, or coordinate through the other.

## Oracle

Two caller fixtures pass in CI:

1. A Bitterblossom task fixture creates a `ReviewRequest.v1`, invokes Cerberus,
   stores the artifact under its run ledger, and never imports Olympus code or
   Argus types.
2. An Olympus Argus fixture creates a `ReviewRequest.v1`, invokes Cerberus,
   validates the returned artifact, and keeps all posting policy
   (activation gate, stale-head suppression, marker dedupe, inline caps) inside
   Olympus.

The tests must fail if either caller references the other's repo path, package,
or type names.

## Verification System

- `cargo test --workspace caller_contracts`
- `cargo run --locked -p cerberus-cli -- validate fixtures/callers/bitterblossom-task.json fixtures/callers/olympus-argus.json`
- A repo-local contract lint that scans adapter fixtures for forbidden
  cross-caller imports/references.
- Consumer-side integration tests in Bitterblossom and Olympus once the core
  fixture path exists.

## Scope

In scope:

- Adapter SDK types and examples for caller-owned acquisition/rendering.
- GitHub request acquisition fixture for PR-shaped inputs.
- Artifact projection usable by Olympus posting policy.
- Artifact storage/receipt conventions usable by Bitterblossom run ledgers.
- Static guard documenting and testing the no-caller-coupling rule.

Out of scope:

- Moving Bitterblossom's event plane into Cerberus.
- Moving Olympus Argus posting policy into Cerberus.
- Making either caller depend on the other's queue, marker, or task model.

## Evidence

- Rendered implementation plan:
  `docs/shaping/002-independent-caller-adapters-plan.html`
- Bitterblossom defines itself as the event plane with task/agent/trigger/run
  primitives and a Rust spine.
- Olympus Argus already owns strict artifact validation, stale-head suppression,
  duplicate markers, and GitHub posting policy.
- Cerberus ADR 004 points toward a provider-agnostic execution boundary that
  adapters can target.

## Child Work

1. Done: define `cerberus-adapter` request builder APIs.
2. Done: add Bitterblossom fixture and storage receipt example.
3. Done: add Olympus Argus fixture and artifact projection example.
4. Done: add no-cross-caller-reference guard.
5. Done: document ownership boundaries in `docs/ARCHITECTURE.md` after
   fixtures pass.
6. Done: add consumer-side integration tests in Bitterblossom and Olympus.

## Implementation Receipt

First local adapter delivery, 2026-06-18:

- Added `crates/cerberus-adapter` as a consumer-side SDK over
  `ReviewRequest.v1` and `ReviewRunArtifact.v1`.
- Added a generic `CallerReviewRequestBuilder`, a
  `BitterblossomRunReceipt` ledger projection, and an
  `OlympusArgusProjection` inline-comment projection.
- Added checked-in caller fixtures:
  `fixtures/callers/bitterblossom-task.json` and
  `fixtures/callers/olympus-argus.json`.
- Added a static guard that rejects sibling caller references in fixture text.
- Local proof: `cargo test --workspace caller_contracts` passed with both
  caller fixtures invoking the fake core and validating the returned artifact.

This first receipt proved the local contract shape before consumer-side proof
landed in the real Bitterblossom and Olympus repositories.

Consumer-side integration delivery, 2026-06-19:

- Added rendered follow-up plan:
  `docs/shaping/002-consumer-integration-tests-plan.html`.
- Bitterblossom branch `bb/build/074-artifact-contract` now has
  `runs_export_carries_cerberus_review_artifact_report`, which runs a local
  harness that writes a Cerberus `ReviewRunArtifact.v1` as required
  `REPORT.json`, exports `bb.run_telemetry.v1`, follows the attempt artifact
  directory pointer, and verifies the preserved artifact without referencing
  Olympus.
- Olympus branch `cerberus/002-consumer-integration` now has Argus poster
  coverage for `ReviewRunArtifact.v1`: the poster translates Cerberus
  severities and citations into Argus comments, rejects stale
  `reviewed_head_sha` values, and keeps duplicate suppression, head freshness,
  inline caps, and marker recording in Olympus.
- Focused proof:
  `cargo test runs_export_carries_cerberus_review_artifact_report --test run_export`
  in Bitterblossom and `npm run test -- argus-review-poster` in Olympus.
- Full consumer proof:
  `./scripts/verify.sh` passed in Bitterblossom. Olympus passed
  `PATH=/Users/phaedrus/.hermes/node/bin:$PATH npm run lint`,
  `PATH=/Users/phaedrus/.hermes/node/bin:$PATH npm run test` (98 files,
  1485 passing, 1 skipped), `PATH=/Users/phaedrus/.hermes/node/bin:$PATH npm run typecheck`,
  and `dagger call check --source=.` (`ALL GATES GREEN`, including coverage,
  build, prod audit, secrets scan, docker smoke, and contract checks; Dagger
  coverage leg reported 97 files passed, 1 skipped, 1481 tests passed, and 5
  skipped).
- Consumer closeout evidence after committing the sibling changes:
  Bitterblossom commit `316e5a5` leaves
  `git status --short --branch --untracked-files=all` at
  `## bb/build/074-artifact-contract...origin/bb/build/074-artifact-contract [ahead 1]`;
  `git rev-list --left-right --count HEAD...origin/bb/build/074-artifact-contract`
  reports `1 0`. Olympus commit `46508b6` leaves
  `git status --short --branch --untracked-files=all` at
  `## cerberus/002-consumer-integration`; that branch has no upstream
  configured yet.
- Cerberus contract/regression proof:
  `cargo test --workspace caller_contracts`,
  `cargo run --locked -p cerberus-cli -- validate fixtures/callers/bitterblossom-task.json fixtures/callers/olympus-argus.json`,
  `cd cerberus-elixir && mix test` (360 tests, 0 failures),
  `cd cerberus-elixir && mix format --check-formatted`, shellcheck over the
  shell scripts present in this checkout, and `node --check bin/cerberus.js`.

Closeout recheck, 2026-06-19:

- Cerberus focused contract proof still passes:
  `cargo test --workspace caller_contracts` and
  `cargo run --locked -p cerberus-cli -- validate fixtures/callers/bitterblossom-task.json fixtures/callers/olympus-argus.json`.
- Bitterblossom branch `bb/build/074-artifact-contract` still passes
  `cargo test runs_export_carries_cerberus_review_artifact_report --test run_export`
  at commit `316e5a5`.
- Olympus branch `cerberus/002-consumer-integration` still passes
  `PATH=/Users/phaedrus/.hermes/node/bin:$PATH npm run test -- argus-review-poster`
  from a temporary worktree at commit `46508b6` after `npm ci`
  (1 file, 16 tests).
- Publication status is deliberately not overstated: Bitterblossom remains one
  local commit ahead of `origin/bb/build/074-artifact-contract`, and Olympus
  branch `cerberus/002-consumer-integration` has no upstream and is one commit
  ahead of, four commits behind, current `main`. That is branch-disposition work,
  not an unresolved caller-adapter contract gap.

## Notes

This ticket depends on backlog 001's schema and fake-runner path.
