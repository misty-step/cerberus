# Rust Harness Runtime Boundary

Snapshot date: 2026-06-18.

Backlog 007 moves `cerberus-core` review execution behind a Rust harness
boundary without adding live provider or shell execution yet.

## Contract

`ReviewHarness` is the narrow execution interface:

```text
ReviewerConfig + ReviewRequest.v1 -> ReviewerArtifact.v1
```

The core still owns:

- request and config validation
- artifact identity, finding citation coverage, and verdict consistency checks
  against the configured reviewer and request
- aggregation, dedupe, coverage, cost, reserves, overrides, and rendering
- degraded artifact creation when a harness fails or returns an invalid artifact

The harness owns only how an individual reviewer artifact is produced.

## Current Implementations

- `DeterministicHarness`: preserves the existing fixture/offline behavior.
- Test harnesses: prove that arbitrary reviewer artifacts can feed aggregation
  and that bad runner output becomes degraded review evidence.

## Not Yet Implemented

- live Pi, Goose, OpenCode, OMP, or Sprites execution
- provider/network clients
- shell command sandboxing
- hosted API replacement

Those belong behind this boundary, not inside the aggregation path.

## Verification

```bash
cargo test --workspace harness_runtime
cargo run --locked -p cerberus-cli -- review --fixture fixtures/review-request/local-diff.json --out tmp/harness-runtime-review
cargo run --locked -p cerberus-cli -- validate tmp/harness-runtime-review/review-run-artifact.json
```
