# 015 - Peer Harness Execution Plan

Status: implemented-local
Priority: P0
Type: epic
Created: 2026-06-18

## Goal

Make live peer harness execution inspectable as a schema-valid artifact before
making it executable.

Backlogs 011 and 012 proved file handoff, prompt rendering, exact transcript
parsing, and fail-closed live mode. This slice adds the missing operator proof:
given a reviewer/request input and a peer harness profile, Cerberus writes the
exact live execution contract it would use later, including command, args,
prompt mode, environment requirements, transcript markers, timeout, and
unsupported boundaries.

## Verification System

- Claim: operators can review the live peer execution contract without spending
  provider budget or invoking peer CLIs.
- Falsifier: the plan leaves `{model}` unresolved, omits required environment
  status, hides output markers, or lets `CERBERUS_PEER_HARNESS_LIVE=1` execute
  Pi, Goose, OpenCode, OMP, or OpenRouter.
- Driver: `cerberus-peer-harness --execution-plan-output <path>`.
- Grader: `cerberus-cli validate <plan>`, focused Rust tests, and a manual live
  fail-closed invocation.
- Evidence packet: `tmp/peer-runner-execution-plan.json`,
  `tmp/peer-runner-live-plan.json`, and this backlog receipt.
- Cadence: before live adapter implementation and before any eval budget spend.

## Oracle

Cerberus can run:

```bash
cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- \
  --harness pi \
  --input fixtures/harnesses/peer-runner-input.json \
  --output tmp/peer-runner-artifact.json \
  --execution-plan-output tmp/peer-runner-execution-plan.json

cargo run --locked -p cerberus-cli -- validate \
  tmp/peer-runner-execution-plan.json
```

and receive a schema-valid `PeerHarnessExecutionPlan.v2` while the default
runner output remains the degraded offline `ReviewerArtifact.v1`.

`CERBERUS_PEER_HARNESS_LIVE=1` may write the same plan but must still fail
closed before invoking any peer harness or provider.

## Scope

In scope:

- `PeerHarnessExecutionPlan.v2` schema and validation.
- `cerberus-peer-harness --execution-plan-output <path>`.
- Environment availability/missing-env reporting without writing secret values.
- Resolved peer args where `{model}` is replaced and `{prompt}` remains a
  placeholder.
- Tests for plan validation and fail-closed live-mode plan output.
- Docs and retirement inventory updates.

Out of scope:

- Invoking Pi, Goose, OpenCode, or OMP.
- Calling OpenRouter or any paid provider.
- Provider budget approval or retry policy.
- Ranking harness/model quality.
- Changing production defaults.

## Evidence

- Backlog 010 provides validated peer harness command profiles.
- Backlog 011 provides the peer runner and offline degraded artifact.
- Backlog 012 provides deterministic prompt rendering and transcript parsing.
- Backlog 014 refreshed current harness/model catalog evidence.
- `cargo test --workspace peer_harness_execution_plan`
- `cargo test -p cerberus-cli --test peer_harness_command`
- `cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- --harness pi --input fixtures/harnesses/peer-runner-input.json --output tmp/peer-runner-artifact.json --execution-plan-output tmp/peer-runner-execution-plan.json`
- `cargo run --locked -p cerberus-cli -- validate tmp/peer-runner-execution-plan.json`
- `cargo run --locked -p cerberus-cli -- validate tmp/peer-runner-artifact.json`
- `CERBERUS_PEER_HARNESS_LIVE=1 cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- --harness pi --input fixtures/harnesses/peer-runner-input.json --output tmp/peer-runner-live-artifact.json --execution-plan-output tmp/peer-runner-live-plan.json` returned non-zero before provider invocation.
- `cargo run --locked -p cerberus-cli -- validate tmp/peer-runner-live-plan.json`
- `test ! -e tmp/peer-runner-live-artifact.json`

## Result

`PeerHarnessExecutionPlan.v2` is now schema-validated and emitted by
`cerberus-peer-harness --execution-plan-output`. The plan records the exact peer
command, resolved args, prompt/output contract, timeout, environment variable
names and availability, transcript markers, unsupported boundaries, and whether
live mode was requested.

Live mode remains fail-closed. This slice does not invoke peer CLIs, call
OpenRouter, spend provider budget, or rank harness/model quality.
