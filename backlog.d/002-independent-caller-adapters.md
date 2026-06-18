# 002 - Independent Caller Adapters

Status: implemented-local-fixtures
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
6. Remaining: add consumer-side integration tests in Bitterblossom and Olympus.

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

This receipt proves the local contract shape. It does not yet prove that the
real Bitterblossom and Olympus repositories have switched to these fixtures.

## Notes

This ticket depends on backlog 001's schema and fake-runner path.
