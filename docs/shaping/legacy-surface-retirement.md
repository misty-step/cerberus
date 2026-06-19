# Legacy Surface Retirement Inventory

Snapshot date: 2026-06-19.

The authoritative machine-checked inventory is
`docs/shaping/legacy-surface-retirement.json`. This document is the readable
table for backlog 005.

## Validation

```bash
cargo run --locked -p cerberus-cli -- validate-retirement docs/shaping/legacy-surface-retirement.json
cargo run --locked -p cerberus-cli -- validate docs/shaping/legacy-surface-retirement.json
```

## Retirement Table

| Surface | Decision | Parity | Replacement or Keep Reason | Next Action |
|---|---|---|---|---|
| `root-github-action` | keep compatibility | compatibility only | Existing consumers call `misty-step/cerberus` through `action.yml`. | Keep the public input/output contract stable while the Rust dispatcher remains the active entrypoint. |
| `dispatch-shell-client` | port to Rust | covered by Rust fixture | Rust GitHub Action adapter backed by `cerberus-cli` and `ReviewRequest.v1`; backlog 021 covers event preflight/request construction, backlog 023 covers dispatch decision fixtures, backlog 024 covers Rust HTTP/output command behavior, backlog 025 wires the public action to Rust, and backlog 026 archives the shell file in `e916c7b9d893e57ed0edfc0d04858fb8d82b67d5`. | Keep the Rust GitHub Action dispatcher covered by action-entrypoint and hosted-dispatch gates. |
| `node-scaffolder` | port to Rust | covered by Rust fixture | `cerberus-cli init` owns deterministic workflow-file scaffolding, hidden TTY prompt, and `gh secret set`; the unpublished npm wrapper was deleted after registry evidence showed no live package. | Keep Rust setup covered; add a native package distribution later only if a real consumer requires it. |
| `elixir-http-api` | port to Rust | pending | Rust hosted API compatibility adapter; POST ingress validation, offline `ReviewRequest.v1` acquisition, service response fixtures, bounded local HTTP listener smoke, stateful local POST/GET store replay, local queued-review worker completion with `ReviewRunArtifact.v1`, and the versioned `HostedApiReviewStore` state contract are fixture-backed. Production queue/store lifecycle, deployment smoke, live GitHub acquisition, and provider-backed reviewer execution remain pending. | Add production Rust queue/store lifecycle, live GitHub acquisition, and deployment smoke before cutting over from Elixir. |
| `elixir-review-execution` | port to Rust | pending | `cerberus-core` reviewer execution and harness runtime, including a hosted API worker fixture that executes a queued review through Rust core into `ReviewRunArtifact.v1`. | Port routing and budget-approved provider-backed peer evals. |
| `elixir-verdict-store` | port to Rust | pending | `ReviewRunArtifact.v1` generation plus `FileReviewRunArtifactStore` for immutable, schema-valid receipt persistence, and `HostedApiReviewStore.v1` for validated local hosted queue/store state. Hosted/API completed responses can carry a validated artifact that the Rust action dispatcher persists when a store root is explicitly provided. Legacy SQLite tables are internal runtime state, not the cross-harness evidence contract; SQLite compatibility is intentionally not required for Rust cutover unless a concrete historical database consumer appears. | Add production Rust hosted queue/store lifecycle proof before retiring the Elixir store; do not build a SQLite bridge without a named historical database consumer. |
| `elixir-review-tools` | port to Rust | pending | Rust harness/provider adapters with typed peer-harness read capabilities; current Pi, Goose, OpenCode, OMP, and fixture profiles declare no Cerberus-granted local repository or GitHub read authority. This is a profile and prompt contract, not runtime sandboxing. | Implement actual Rust GitHub/local read adapters only when a measured harness profile requires those capabilities. |
| `legacy-defaults-and-personas` | port to Rust | pending | Measured `ReviewerConfigPacket.v1` imports from Daedalus or harness/model eval evidence. | Replace static defaults only after live eval evidence. |
| `elixir-release-and-deploy` | archive after parity | pending | Keep only while the hosted API remains Elixir-backed. | Define Rust API deployment smoke before archiving scripts. |
| `historical-walkthroughs-and-artifacts` | archive after parity | intentionally rejected | Evidence artifacts, not active runtime surfaces. `docs/walkthroughs/ARCHIVE.md` indexes current walkthrough, artifact, and raw evidence roots. | Keep the archive index current; move or delete historical material only in a separate archive commit with rollback path preserved. |

## Rule

No entry can be deleted or archived by prose alone. The JSON inventory must name
the replacement or keep reason, parity evidence or intentional rejection,
deletion/archive commit, rollback path, and next action. The validator rejects
archive/delete commits recorded against pending compatibility surfaces.
