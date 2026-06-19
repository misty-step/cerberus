# 024 - Hosted API HTTP Dispatch

Status: implemented
Priority: P0
Type: compatibility
Created: 2026-06-19

## Goal

Add the Rust command that can perform the hosted API dispatch loop for GitHub
Actions: POST `/api/reviews`, poll `GET /api/reviews/:id`, write GitHub output
values, write verdict JSON when `RUNNER_TEMP` is present, and exit according to
the hosted dispatch decision. This removes the last network-only behavior from
the shell client without yet changing `action.yml`.

## Verification System

- Claim: `cerberus-cli github-action-dispatch` can run the hosted API
  POST/poll/output path against a local fake API without shelling to `curl`.
- Falsifier: the fake API receives the wrong method, path, bearer auth, payload,
  model, or GitHub token; the command writes wrong `review-id` or `verdict`
  outputs; fail-on-verdict exits zero; verdict JSON is missing; or fork skip
  still requires hosted API secrets.
- Driver:
  `cargo test -p cerberus-cli --test github_action_dispatch`.
- Grader: integration assertions over captured HTTP requests, output-file
  contents, decision JSON, verdict JSON, process status, and skip behavior.
- Evidence packet: `tmp/hosted-api-http-dispatch-2026-06-19/`.
- Cadence: before wiring `action.yml` to the Rust command.

## Scope

In scope:

- Refactor hosted dispatch into a fakeable Rust transport loop.
- Add `cerberus-cli github-action-dispatch`.
- Use a blocking Rust HTTP client for real POST/poll transport.
- Append GitHub Actions output values to the configured output file.
- Capture verdict JSON under `RUNNER_TEMP/cerberus-api-verdict.json`.
- Add local fake-server integration tests.

Out of scope:

- Replacing `action.yml` or deleting `dispatch.sh`.
- Live hosted Cerberus credentials.
- Porting the Elixir hosted API implementation.
- Changing review execution, model defaults, or harness/model evaluation.

## Evidence

- Plan: `docs/shaping/024-hosted-api-http-dispatch-plan.html`
- Focused adapter and CLI tests:
  - `cargo test --workspace hosted_api`
  - `cargo test -p cerberus-cli --test github_action_dispatch`
- QA packet:
  `tmp/hosted-api-http-dispatch-2026-06-19/`
- Full gates: see final delivery receipt for this commit.

## Result

Implemented. The Rust CLI now has an env-compatible
`github-action-dispatch` command that sends the hosted API payload, polls the
review, writes GitHub output values, writes verdict JSON, and exits non-zero for
`FAIL` when fail-on-verdict is enabled. `dispatch.sh` and `action.yml` remain
the active compatibility entrypoint until a follow-up slice wires the composite
action to this command and proves consumer workflow parity.
