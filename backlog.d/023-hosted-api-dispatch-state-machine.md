# 023 - Hosted API Dispatch State Machine

Status: implemented
Priority: P0
Type: compatibility
Created: 2026-06-19

## Goal

Move the hosted API dispatch and polling decisions currently embedded in
`dispatch.sh` into a pure Rust fixture state machine. This proves the behavior a
future Rust HTTP transport must preserve before the composite action stops
calling the shell client, with one intentional hardening: an accepted POST
response without `review_id` fails closed instead of polling an empty URL.

## Verification System

- Claim: Rust can reproduce hosted API dispatch, polling, verdict output,
  timeout, poll-error exhaustion, review failure, malformed dispatch response,
  and fail-on-verdict behavior from checked transcripts.
- Falsifier: any transcript emits the wrong outcome, simulated exit code,
  review-id, verdict, elapsed poll budget, or GitHub output map.
- Driver:
  `cerberus-cli hosted-api-dispatch-fixture --transcript <fixture> --out <decision>`.
- Grader: focused `hosted_api` Rust tests, CLI fixture output inspection,
  retirement inventory validation, full repo gates, and fresh critic.
- Evidence packet: `tmp/hosted-api-dispatch-2026-06-19/`.
- Cadence: before adding real Rust HTTP POST/poll transport or changing
  `action.yml`.

## Scope

In scope:

- Add a Rust adapter state machine for hosted API transcript fixtures.
- Add a CLI fixture command that writes the simulated action decision as JSON.
- Add checked transcripts for PASS, fail-on-verdict, POST rejection, malformed
  `review_id`, poll-error exhaustion, hosted review failure, and timeout.
- Update backlog, architecture, and legacy retirement docs.

Out of scope:

- Making live network calls.
- Adding an HTTP client dependency.
- Replacing `dispatch.sh` or `action.yml`.
- Fetching GitHub context or reviewer semantic context.
- Running paid harness/model evaluations or changing reviewer defaults.

## Evidence

- Plan: `docs/shaping/023-hosted-api-dispatch-state-machine-plan.html`
- Focused test:
  `cargo test --workspace hosted_api`
- CLI fixture driver:
  `for f in fixtures/github-actions/hosted-api-*.json; do name=$(basename "$f" .json); cargo run --locked -q -p cerberus-cli -- hosted-api-dispatch-fixture --transcript "$f" --out "tmp/hosted-api-dispatch-2026-06-19/$name.decision.json"; done`
- Fixture summary:

| Fixture | Outcome | Exit | Review id | Verdict | Elapsed | Polls |
|---|---|---:|---|---|---:|---:|
| `hosted-api-dispatch-rejected.json` | `dispatch_rejected` | 1 |  | `SKIP` | 0 | 0 |
| `hosted-api-fail-verdict.json` | `completed` | 1 | `review-459` | `FAIL` | 5 | 1 |
| `hosted-api-missing-review-id.json` | `invalid_dispatch_response` | 1 |  | `SKIP` | 0 | 0 |
| `hosted-api-pass.json` | `completed` | 0 | `review-459` | `PASS` | 15 | 3 |
| `hosted-api-poll-errors.json` | `poll_errors_exhausted` | 1 | `review-459` | `SKIP` | 10 | 2 |
| `hosted-api-review-failed.json` | `review_failed` | 1 | `review-459` | `SKIP` | 5 | 1 |
| `hosted-api-timeout.json` | `timed_out` | 1 | `review-459` | `SKIP` | 10 | 2 |

## Result

Implemented. The Rust adapter now has a pure hosted API dispatch state machine
and the CLI can write inspectable fixture decisions. Elapsed seconds follow the
shell client's sleep-before-poll accounting, and omitted `fail_on_verdict`
defaults to the action-compatible `true`. The shell client remains the
production compatibility path until a later slice adds real Rust HTTP transport
and GitHub Actions output-file wiring.
