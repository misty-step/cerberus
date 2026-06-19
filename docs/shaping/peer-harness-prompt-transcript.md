# Peer Harness Prompt and Transcript Fixtures

Snapshot date: 2026-06-19.

Backlog 012 adds deterministic prompt rendering and exact transcript fixture
parsing to `cerberus-peer-harness`. This is still not live model execution.

## Prompt Output

`--prompt-output <path>` writes the prompt the runner would hand to the selected
peer harness. The prompt includes:

- reviewer id, perspective, and model
- selected peer harness id and command
- declared local repository and GitHub read capabilities
- request id, title, description, acceptance notes, changed files, and diff
- the `ReviewerArtifact.v1` output contract and validation rules

Each read capability is scoped independently. A true `local_repo_read` value
authorizes only local repository inspection, and a true `github_read` value
authorizes only GitHub inspection. When either capability is false, the prompt
tells the peer reviewer not to claim inspection of that source.

Prompt rendering is deterministic and fixture-backed. Prompt optimization and
model-specific variants are later eval work.

## Transcript Fixture Parsing

`--transcript <path>` reads a local transcript fixture and extracts exactly one
artifact block:

```text
CERBERUS_REVIEWER_ARTIFACT_JSON_BEGIN
{ ... ReviewerArtifact.v1 JSON ... }
CERBERUS_REVIEWER_ARTIFACT_JSON_END
```

The parser does not infer findings from prose. It parses only the marked JSON
block, then validates the artifact through the same core reviewer/request
acceptance helper used by `ReviewHarness` aggregation.

## Verification

```bash
cargo test --workspace peer_harness_runner
cargo test -p cerberus-cli --test peer_harness_command
mkdir -p tmp
cargo run --locked -p cerberus-cli --bin cerberus-peer-harness -- --harness pi --input fixtures/harnesses/peer-runner-input.json --output tmp/peer-runner-artifact.json --prompt-output tmp/peer-runner-prompt.txt --transcript fixtures/harnesses/peer-transcript-with-finding.txt
cargo run --locked -p cerberus-cli -- validate tmp/peer-runner-artifact.json
```

The checked transcript fixture emits a completed `WARN` artifact with one minor
finding. The default no-transcript runner path remains degraded `SKIP`.

## Live Boundary

Backlog 016 adds fixture-backed live command invocation. Backlog 017 adds
private prompt-file transport. Pi, Goose, OpenCode, OMP, OpenRouter, and other
provider-backed profiles remain budget-gated by
`CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK=1` and still require explicit
harness/model evaluation before promotion.
