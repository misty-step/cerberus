# 002 - Independent Caller Adapters

Status: shaped
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

- Bitterblossom defines itself as the event plane with task/agent/trigger/run
  primitives and a Rust spine.
- Olympus Argus already owns strict artifact validation, stale-head suppression,
  duplicate markers, and GitHub posting policy.
- Cerberus ADR 004 points toward a provider-agnostic execution boundary that
  adapters can target.

## Child Work

1. Define `cerberus-adapter` request builder APIs.
2. Add Bitterblossom fixture and storage receipt example.
3. Add Olympus Argus fixture and artifact projection example.
4. Add no-cross-caller-reference guard.
5. Document ownership boundaries in `docs/ARCHITECTURE.md` after fixtures pass.

## Notes

This ticket depends on backlog 001's schema and fake-runner path.
