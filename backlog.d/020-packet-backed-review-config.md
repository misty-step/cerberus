# 020 - Packet-Backed Review Config

Status: implemented
Priority: P0
Type: feature
Created: 2026-06-19

## Goal

Let Rust review commands run directly from a measured `ReviewerConfigPacket.v1`
without hand-extracting the embedded `ReviewConfig.v1`.

Backlog 019 can produce sandbox-only candidate packets from live eval evidence,
and backlog 004 can validate and dry-run those packets. The next bridge is
operational: `review` and `review-local` should accept a packet path as a
config source while preserving packet validation, sandbox boundaries, and
default immutability.

## Verification System

- Claim: a validated sandbox reviewer config packet can drive Rust fixture and
  local-diff reviews directly.
- Falsifier: packet-backed review bypasses `ReviewerConfigPacket.v1`
  validation, allows both raw config and packet inputs at once, mutates
  defaults, or emits invalid review artifacts.
- Driver:
  `cerberus-cli review --fixture <request.json> --config-packet <packet.json> --out <dir>`
  and
  `cerberus-cli review-local --diff-file <diff> --config-packet <packet.json> --out <dir>`.
- Grader: schema validation of emitted `ReviewRunArtifact.v1`, focused parser
  tests, and a negative CLI run for mutually exclusive config inputs.
- Evidence packet: `tmp/reviewer-config/packet-review/` and
  `tmp/reviewer-config/packet-local-review/`.
- Cadence: after candidate packet generation and before any default promotion
  or caller integration uses a measured config.

## Scope

In scope:

- `--config-packet <ReviewerConfigPacket.v1.json>` for `review`.
- `--config-packet <ReviewerConfigPacket.v1.json>` for `review-local`.
- Mutual exclusion with `--config`.
- Reuse existing packet validation and embedded config hash checks.
- Docs, tests, QA, and backlog updates.

Out of scope:

- Production approval, default mutation, or config installation.
- Signature verification for non-sandbox packets.
- Provider-backed eval spend.
- New packet or import-report schemas.

## Evidence

- `cargo test -p cerberus-cli local_review_args`
- `cargo check -p cerberus-cli`
- `cargo run --locked -p cerberus-cli -- review --fixture fixtures/review-request/clean.json --config-packet fixtures/reviewer-config-packets/daedalus-sandbox-reviewer-config.json --out tmp/reviewer-config/packet-review`
- `cargo run --locked -p cerberus-cli -- review-local --diff-file fixtures/local-review/local.diff --config-packet fixtures/reviewer-config-packets/daedalus-sandbox-reviewer-config.json --out tmp/reviewer-config/packet-local-review`
- `cargo run --locked -p cerberus-cli -- validate tmp/reviewer-config/packet-review/review-run-artifact.json tmp/reviewer-config/packet-local-review/review-request.json tmp/reviewer-config/packet-local-review/review-run-artifact.json`
- Negative QA:
  - `review-local --config ... --config-packet ...` rejects with
    `review-local accepts either --config or --config-packet, not both`.
  - `review --config ... --config-packet ...` rejects with
    `review accepts either --config or --config-packet, not both`.
- Fresh-context critic: no blocking issues; non-blocking concern about conflict
  masking was resolved before final gates.
- Final gates:
  - `cargo test --workspace`
  - `cargo fmt --all -- --check`
  - `git diff --check`
  - `shellcheck dispatch.sh fixtures/harnesses/command-reviewer.sh fixtures/harnesses/live-peer-reviewer.sh`
  - `node --check bin/cerberus.js`
  - `cd cerberus-elixir && mix test`
  - `cd cerberus-elixir && mix format --check-formatted`

Packet-backed fixture review result:

- `tmp/reviewer-config/packet-review/review-run-artifact.json`
- verdict: `PASS`
- findings: `0`
- reviewers: `correctness`, `security`, `testing`

Packet-backed local review result:

- `tmp/reviewer-config/packet-local-review/review-request.json`
- `tmp/reviewer-config/packet-local-review/review-run-artifact.json`
- source: `local_diff`
- changed files: `1`
- verdict: `PASS`
- findings: `0`
- reviewers: `correctness`, `security`, `testing`

## Result

Implemented. `review` and `review-local` can now consume a validated
`ReviewerConfigPacket.v1` directly with `--config-packet`. Raw `--config` and
packet-backed `--config-packet` inputs are mutually exclusive. The bridge uses
existing packet validation and does not approve, install, or mutate production
defaults.
