# 010 - Peer Harness Command Profiles

Status: done
Priority: P0
Type: epic
Created: 2026-06-18

## Goal

Attach Pi, Goose, OpenCode, and OMP to the Rust command-adapter path as
validated profile data before running paid or live model cells.

Backlog 009 proved the `CommandHarness` subprocess protocol. This slice records
the peer harness launch shapes and converts a validated profile into a
`CommandHarness` without putting shell or provider semantics in
`cerberus-core`.

## Oracle

Cerberus accepts a `PeerHarnessCommandProfiles.v3` packet that:

- validates one profile per harness id
- records the CommandHarness protocol runner command and static args
- records the underlying peer CLI command and argument template separately
- declares env requirements, timeout, output contract, and unsupported
  containment boundaries
- can be converted by `cerberus-adapter` into a `CommandHarness`

## Verification System

- `cargo test --workspace peer_harness_command_profiles`
- `cargo test --workspace peer_harness_profile_builds_command_harness`
- `cargo run --locked -p cerberus-cli -- validate fixtures/harnesses/peer-command-profiles.json`
- full repo gates continue to pass

## Scope

In scope:

- Rust schema for peer command profile packets.
- Adapter conversion from one validated profile to `CommandHarness`.
- Checked-in Pi, Goose, OpenCode, and OMP profile fixture grounded in local
  `--help` output.
- Docs that make the wrapper/protocol boundary explicit.

Out of scope:

- Implementing `cerberus-peer-harness`.
- Calling paid providers or live OpenRouter models.
- Ranking harness/model quality.
- Promoting reviewer defaults.
- Claiming sandbox containment beyond the existing process-group cleanup.

## Evidence

- Backlog 009 provides `CommandHarness` and private temp/process-group cleanup.
- `docs/shaping/harness-model-evaluation.md` records the harness/model matrix
  and current model candidates.
- `docs/shaping/legacy-surface-retirement.json` marks Elixir review execution
  pending until Pi, Goose, OpenCode, and OMP command profiles exist behind the
  Rust harness boundary.

## Implementation Receipt

First local delivery, 2026-06-18:

- Added initial `PeerHarnessCommandProfiles.v2` schema and validation.
- Added a checked-in Pi, Goose, OpenCode, and OMP profile fixture.
- Enforced the wrapper/peer boundary: v2 profiles must use
  `cerberus-peer-harness --harness <harness_id>` as the protocol runner and
  must not execute the raw peer CLI directly.
- Enforced argv prompt handoff: argv/template peer profiles must contain
  exactly one standalone `{prompt}` argument.
- Backlog 017 later bumps the current profile packet to v3 for private
  prompt-file transport.
- Added adapter conversion from validated profile data to `CommandHarness`.
- Added CLI validation support and docs for the profile boundary.
- Verified with:
  - `cargo test --workspace peer_harness_command_profiles`
  - `cargo test --workspace peer_harness_profile_builds_command_harness`
  - `cargo run --locked -p cerberus-cli -- validate fixtures/harnesses/peer-command-profiles.json`
  - `cargo test --workspace`
  - `cargo fmt --all -- --check`
  - `git diff --check`
  - `shellcheck dispatch.sh fixtures/harnesses/command-reviewer.sh`
  - `node --check bin/cerberus.js`
  - `cd cerberus-elixir && mix format --check-formatted`
  - `cd cerberus-elixir && mix test`

OpenCode profile hardening, 2026-06-19:

- The first provider-backed live smoke in backlog 006 showed every OpenCode
  row failing before model execution because the static reviewer instruction was
  parsed as an additional `--file` attachment:
  `File not found: Follow the attached Cerberus reviewer prompt exactly.`
- Updated the checked OpenCode profile to insert `--` after
  `--file {prompt_file}`, terminating OpenCode's file array before the
  positional reviewer message.
- Added schema fixture regression coverage so the OpenCode profile must keep
  `--file`, `{prompt_file}`, `--`, and the static message in that order.
- No-spend evidence packet:
  `tmp/opencode-profile-hardening-2026-06-19/`.
  - Execution plan:
    `opencode-plan.json`
    (`sha256:d551d4d2cf9c6280ce31b7956be949cd805776f726ef45dba25eb8c86d73c15a`)
    shows `--file`, `{prompt_file}`, `--`, then the reviewer message.
  - OpenCode separator probe:
    `opencode-separator-probe.txt`
    (`sha256:c5c2da713873520d3c9d3923f8e24a9590031d2de0d386b7f4eb9290ec0cea1b`)
    reaches the intentionally invalid model lookup and does not report
    `File not found: Follow the attached Cerberus reviewer prompt exactly.`
- This hardens the invocation profile only. It does not rerun paid provider
  cells, rank OpenCode quality, or promote reviewer defaults.
