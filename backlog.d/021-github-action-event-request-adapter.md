# 021 - GitHub Action Event Request Adapter

Status: implemented
Priority: P0
Type: feature
Created: 2026-06-19

## Goal

Move the first GitHub Action dispatch responsibility into Rust: given a
`pull_request` event payload and a checked unified diff, build a validated
`ReviewRequest.v1` or return an explicit skip decision for fork and draft pull
requests.

This is the smallest useful step toward retiring `dispatch.sh`. It proves the
GitHub Actions event boundary without mixing hosted API POST/poll behavior into
the request adapter.

## Verification System

- Claim: Rust can turn GitHub Actions `pull_request` event data plus a diff
  into a source-agnostic `ReviewRequest.v1`, while preserving fork and draft
  skip behavior.
- Falsifier: fork/draft events create review requests, same-repo events fail to
  validate, changed-file metadata drifts from the diff, or the adapter pulls
  hosted API, token, polling, or posting behavior into core request building.
- Driver:
  `cerberus-cli github-action-request --event <event.json> --diff-file <diff> --out <request.json>`.
- Grader: focused Rust tests over same-repo, fork, draft, malformed diff, and
  CLI fixture QA followed by `cerberus-cli validate <request.json>`.
- Evidence packet: `tmp/github-action-request/`.
- Cadence: before replacing shell dispatch or wiring a Rust GitHub Action
  runner.

## Scope

In scope:

- Rust adapter function for GitHub Actions pull-request event preflight.
- Syntax-level diff parsing shared by local review and the GitHub event
  adapter.
- CLI fixture command that writes a validated `ReviewRequest.v1` for same-repo
  PRs.
- Fork and draft skip decisions represented as structured Rust output.
- Fixtures, docs, tests, QA, and retirement-inventory evidence.

Out of scope:

- Calling GitHub APIs.
- Calling the hosted Cerberus API.
- Polling, timeout, fail-on-verdict, or GitHub output writing.
- Replacing `action.yml` or deleting `dispatch.sh`.
- Semantic linked-issue, acceptance, or context inference from PR prose.

## Evidence

- `cargo test -p cerberus-adapter github_action`
- `cargo test -p cerberus-adapter git_diff`
- `cargo test -p cerberus-cli local_review`
- Same-repo CLI QA:
  `cargo run --locked -p cerberus-cli -- github-action-request --event fixtures/github-actions/pull-request-opened.json --diff-file fixtures/github-actions/pull-request.diff --out tmp/github-action-request/review-request.json --run-id gha-run-021`
- Schema validation:
  `cargo run --locked -p cerberus-cli -- validate tmp/github-action-request/review-request.json`
- Fork skip QA:
  `cargo run --locked -p cerberus-cli -- github-action-request --event fixtures/github-actions/pull-request-fork.json --diff-file /no/such/diff.patch --out tmp/github-action-request/fork-no-diff-review-request.json --run-id gha-run-021`
  wrote `{"decision":"skip","reason":"fork_pull_request",...}` and no request
  file, without requiring a readable diff.
- Draft skip QA:
  `cargo run --locked -p cerberus-cli -- github-action-request --event fixtures/github-actions/pull-request-draft.json --diff-file /no/such/diff.patch --out tmp/github-action-request/draft-no-diff-review-request.json --run-id gha-run-021`
  wrote `{"decision":"skip","reason":"draft_pull_request",...}` and no request
  file, without requiring a readable diff.
- Missing head repo QA:
  `cargo run --locked -p cerberus-cli -- github-action-request --event fixtures/github-actions/pull-request-missing-head-repo.json --diff-file /no/such/diff.patch --out tmp/github-action-request/missing-head-repo-review-request.json --run-id gha-run-021`
  wrote a fork skip and no request file.
- Diff parser regression:
  `cargo test -p cerberus-adapter git_diff` covers unquoted paths with spaces.
- Generated request evidence:
  `tmp/github-action-request/review-request.json`
  - request id: `github-pr-misty-step-cerberus-459-abc123def456`
  - caller: `github-actions`, run id `gha-run-021`
  - source: `github_pr` for `misty-step/cerberus#459`
  - files: `README.md` modified with one addition and one deletion;
    `docs/action.md` added with one addition.
- Fresh-context critic: found two blocking parity issues: skip decisions
  requiring readable diff files, and null head repo metadata parse-failing
  instead of skipping. Both were fixed before final gates.
- Fresh-context critic re-review: no blocking findings; confirmed skip-before-diff,
  null head repo skip, unquoted path-with-space parsing, and no API/polling/output
  leakage in the new adapter surface.
- Full gates:
  - `cargo test --workspace`
  - `cargo fmt --all -- --check`
  - `git diff --check`
  - `shellcheck dispatch.sh fixtures/harnesses/command-reviewer.sh fixtures/harnesses/live-peer-reviewer.sh`
  - `node --check bin/cerberus.js`
  - `cargo run --locked -p cerberus-cli -- validate-retirement docs/shaping/legacy-surface-retirement.json`
  - `cargo run --locked -p cerberus-cli -- validate tmp/github-action-request/review-request.json`
  - `jq empty` over all `fixtures/github-actions/*.json` event fixtures
  - `cd cerberus-elixir && mix test`
  - `cd cerberus-elixir && mix format --check-formatted`

## Result

Implemented. `cerberus-adapter` now owns syntax-level Git diff parsing and a
GitHub Actions pull-request event adapter. `cerberus-cli
github-action-request` writes a validated `ReviewRequest.v1` for same-repo PRs
and returns structured skip decisions for fork and draft PRs. The slice does
not replace `dispatch.sh`, call GitHub, call the hosted API, poll for verdicts,
or write GitHub Actions outputs.
