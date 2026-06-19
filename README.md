# Cerberus

Cerberus is a context-adaptive AI code review runner. It accepts a
source-agnostic `ReviewRequest.v1`, gives one master reviewer the available
context through a selected agent substrate, validates the returned
`ReviewArtifact.v1`, and renders the result for callers such as local scripts
or future GitHub adapters.

There are no predefined reviewer subagents. The Cerberus master may launch
ephemeral substrate subagents at runtime when the diff and context call for
them. Rust owns the contracts, capability boundaries, receipts, validation, and
rendering.

OpenCode is the preferred production-oriented substrate because its
server/session-first shape fits durable automated review better than a
terminal-first wrapper. OMP remains supported as a local power-user fallback.

See [spec.md](spec.md) for the locked MVP contract.

## Verify

```sh
./scripts/verify.sh
```

The verification script formats, lints, tests, and runs a deterministic CLI
smoke review through the fixture harness. Evidence is written to
`target/cerberus/`.

## CLI

```sh
cerberus review --request fixtures/requests/diff-only.json \
  --harness fixture \
  --fixture-output fixtures/harness/valid-review.txt \
  --out target/cerberus/artifact.json \
  --markdown target/cerberus/review.md \
  --execution-plan target/cerberus/execution_plan.json

cerberus render --artifact target/cerberus/artifact.json \
  --markdown target/cerberus/review-rendered.md
```

The fixture harness is for deterministic verification. The production path is
the OpenCode harness; OMP is a local fallback.
