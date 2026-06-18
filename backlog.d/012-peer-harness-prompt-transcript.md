# 012 - Peer Harness Prompt and Transcript Fixtures

Status: done
Priority: P0
Type: epic
Created: 2026-06-18

## Goal

Add deterministic prompt rendering and exact transcript fixture parsing to the
Rust `cerberus-peer-harness` runner without invoking Pi, Goose, OpenCode, OMP,
OpenRouter, or paid providers.

Backlog 011 proved the file protocol and offline degraded artifact emission.
This slice proves the next live-adjacent pieces: the prompt a peer harness would
receive and the parser that turns a captured peer transcript into a
`ReviewerArtifact.v1`.

## Oracle

Cerberus can run:

```bash
cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- \
  --harness pi \
  --input fixtures/harnesses/peer-runner-input.json \
  --output tmp/peer-runner-artifact.json \
  --prompt-output tmp/peer-runner-prompt.txt \
  --transcript fixtures/harnesses/peer-transcript-with-finding.txt
```

and receive a valid completed reviewer artifact parsed from the transcript
fixture, after validating reviewer id, perspective, model, findings, verdict,
and exact request coverage through the core artifact acceptance rule.

## Verification System

- `cargo test --workspace peer_harness_runner`
- `cargo test -p cerberus-cli --test peer_harness_command`
- manual runner invocation with `--prompt-output` and `--transcript`
- `cargo run --locked -p cerberus-cli -- validate <emitted ReviewerArtifact.v1>`
- full repo gates continue to pass

## Scope

In scope:

- Public core helper for validating one `ReviewerArtifact.v1` against a
  reviewer/request pair.
- Runner support for `--prompt-output <path>`.
- Runner support for `--transcript <path>` fixture parsing.
- Exact transcript markers around a single JSON artifact block.
- Positive and negative parser tests.
- Command-harness integration test for the transcript fixture path.
- Docs that keep fixture parsing separate from live model execution.

Out of scope:

- Invoking Pi, Goose, OpenCode, or OMP.
- Calling OpenRouter or any provider.
- Inferring findings from free-form transcript prose.
- Prompt optimization or model-specific prompt variants.
- Ranking harness/model quality.

## Evidence

- Backlog 011 provides the runner binary and offline degraded artifact path.
- `crates/cerberus-core` already owns artifact acceptance during
  `ReviewHarness` aggregation.

## Implementation Receipt

First local delivery, 2026-06-18:

- Exposed `validate_reviewer_artifact_for_request` from `cerberus-core` so
  runner-parsed artifacts and harness-returned artifacts share the same
  reviewer/request acceptance rule.
- Tightened completed-artifact verdict consistency so `status: completed` with
  `verdict: SKIP` is rejected and converted to degraded evidence by the harness
  runtime.
- Added `--prompt-output <path>` to `cerberus-peer-harness` for deterministic
  prompt artifact generation.
- Added `--transcript <path>` fixture parsing with exact
  `CERBERUS_REVIEWER_ARTIFACT_JSON_BEGIN` /
  `CERBERUS_REVIEWER_ARTIFACT_JSON_END` markers.
- Added a checked transcript fixture with one completed `WARN` artifact and one
  minor finding.
- Added unit tests for prompt rendering, transcript parsing, missing/duplicate
  marker rejection, completed `SKIP` rejection, live-mode refusal, and offline
  degraded output.
- Added command-harness integration coverage for both the default degraded path
  and the transcript-parsed completed path.
- Documented the prompt/transcript boundary and updated architecture,
  runtime-boundary, profile, backlog, and retirement inventory docs.
- Verified with:
  - `cargo test --workspace peer_harness_runner`
  - `cargo test --workspace harness_runtime_degrades_completed_skip_verdict`
  - `cargo test -p cerberus-cli --test peer_harness_command`
  - `cargo run --locked -p cerberus-cli -- validate-retirement docs/shaping/legacy-surface-retirement.json`
  - `cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- --harness pi --input fixtures/harnesses/peer-runner-input.json --output tmp/peer-runner-artifact.json`
  - `cargo run --locked -p cerberus-cli -- validate tmp/peer-runner-artifact.json`
  - `cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- --harness pi --input fixtures/harnesses/peer-runner-input.json --output tmp/peer-runner-transcript-artifact.json --prompt-output tmp/peer-runner-prompt.txt --transcript fixtures/harnesses/peer-transcript-with-finding.txt`
  - `cargo run --locked -p cerberus-cli -- validate tmp/peer-runner-transcript-artifact.json`
  - `cargo run --locked -p cerberus-cli -- validate fixtures/harnesses/peer-command-profiles.json`
  - `cargo test --workspace`
  - `cargo fmt --all -- --check`
  - `git diff --check`
  - `shellcheck dispatch.sh fixtures/harnesses/command-reviewer.sh`
  - `node --check bin/cerberus.js`
  - `cd cerberus-elixir && mix format --check-formatted`
  - `cd cerberus-elixir && mix test`
