# 013 - Rust Local Review Replay

Status: done
Priority: P0
Type: epic
Created: 2026-06-18

## Goal

Port a concrete local-review entrypoint into the Rust CLI. The command reads a
local git-style diff file, builds a `ReviewRequest.v1`, runs the existing Rust
review core, and writes the same JSON plus Markdown artifacts as
`cerberus-cli review --fixture`.

This is a fixture-backed replacement proof for part of the legacy Elixir local
review surface. It deliberately avoids semantic routing and live provider work.

## Oracle

Cerberus can run:

```bash
cargo run --locked -p cerberus-cli -- review-local \
  --diff-file fixtures/local-review/local.diff \
  --out tmp/local-review

cargo run --locked -p cerberus-cli -- validate \
  tmp/local-review/review-run-artifact.json
```

and receive a schema-valid `ReviewRunArtifact.v1` whose request source is local
diff, whose changed files match the diff, and whose fake-review directive is
detected by the existing deterministic review core.

## Verification System

- `cargo test --workspace local_review`
- manual `review-local` invocation against the checked local diff fixture
- artifact validation with `cerberus-cli validate`
- full repo gates continue to pass

## Scope

In scope:

- CLI command `review-local`.
- Syntax-level parser for git diff headers, file status, and hunk additions /
  deletions.
- Local review fixture diff.
- Tests for modified, added, deleted, renamed/copied, and malformed diff cases.
- Docs and retirement inventory updates.

Out of scope:

- LLM routing or semantic reviewer selection.
- Live peer harness/provider execution.
- Shelling out to `git`.
- Hosted API compatibility.
- Replacing the public GitHub Action path.

## Evidence

- Backlog 007-012 provide the Rust review core, harness boundary, command
  adapter, peer runner, and transcript fixtures.
- Legacy Elixir `Cerberus.CLI` handles local diff review today; this slice ports
  the local diff replay proof, not the full runtime.

## Implementation Receipt

First local delivery, 2026-06-18:

- Added `cerberus-cli review-local --diff-file <diff> --out <dir>` with
  optional `--config`, `--repo-path`, `--request-id`, and `--title` flags.
- Added syntax-level git diff parsing for file headers, added/deleted/renamed/
  copied status markers, and hunk addition/deletion counts.
- Wrote `review-request.json`, `review-run-artifact.json`, and `review-run.md`
  from the Rust review core, matching the existing fixture-review artifact
  surface.
- Added malformed diff, duplicate path, request validation, and argument
  parsing tests.
- Added `fixtures/local-review/local.diff` with the exact
  `CERBERUS_FAKE_FINDING` directive.
- Documented the local replay boundary and updated architecture, backlog, docs
  index, and legacy retirement inventory.
- Verified with:
  - `cargo test --workspace local_review`
  - `cargo fmt --all -- --check`
  - `git diff --check`
  - `cargo run --locked -p cerberus-cli -- review-local --diff-file fixtures/local-review/local.diff --out tmp/local-review`
  - `cargo run --locked -p cerberus-cli -- validate tmp/local-review/review-request.json`
  - `cargo run --locked -p cerberus-cli -- validate tmp/local-review/review-run-artifact.json`
  - `cargo run --locked -p cerberus-cli -- validate-retirement docs/shaping/legacy-surface-retirement.json`
  - `cargo test --workspace`
  - `shellcheck dispatch.sh fixtures/harnesses/command-reviewer.sh`
  - `node --check bin/cerberus.js`
  - `cd cerberus-elixir && mix format --check-formatted`
  - `cd cerberus-elixir && mix test`
