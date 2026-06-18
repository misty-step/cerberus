# Legacy Surface Retirement Inventory

Snapshot date: 2026-06-18.

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
| `root-github-action` | keep compatibility | compatibility only | Existing consumers call `misty-step/cerberus` through `action.yml`. | Keep aligned with dispatch until a Rust action adapter proves the same behavior. |
| `dispatch-shell-client` | port to Rust | pending | Rust GitHub Action adapter backed by `cerberus-cli` and `ReviewRequest.v1`. | Add Rust fixtures for fork skip, draft skip, timeout, poll failure, and fail-on-verdict. |
| `node-scaffolder` | port to Rust | pending | `cerberus-cli init` or equivalent Rust scaffolder. | Fixture generated workflow parity before deprecating Node. |
| `elixir-http-api` | port to Rust | pending | Rust API adapter accepting source-agnostic review requests while preserving public compatibility. | Capture API request/response fixtures and map them to `ReviewRequest.v1`. |
| `elixir-review-execution` | port to Rust | pending | `cerberus-core` reviewer execution and harness runtime. | Port routing, timeout, live transcript capture, and hosted/API review fixtures. |
| `elixir-verdict-store` | port to Rust | pending | `ReviewRunArtifact.v1` generation plus a Rust storage adapter when persistence is needed. | Add Rust fixtures for aggregation, dedupe, override, cost, malformed rows, and persisted replay. |
| `elixir-review-tools` | port to Rust | pending | Rust harness/provider adapters with explicit external boundaries. | Model GitHub/local read tools as adapter capabilities. |
| `legacy-defaults-and-personas` | port to Rust | pending | Measured `ReviewerConfigPacket.v1` imports from Daedalus or harness/model eval evidence. | Replace static defaults only after live eval evidence. |
| `elixir-release-and-deploy` | archive after parity | pending | Keep only while the hosted API remains Elixir-backed. | Define Rust API deployment smoke before archiving scripts. |
| `historical-walkthroughs-and-artifacts` | archive after parity | intentionally rejected | Evidence artifacts, not active runtime surfaces. | Create an archive index before moving or deleting historical walkthrough material. |

## Rule

No entry can be deleted or archived by prose alone. The JSON inventory must name
the replacement or keep reason, parity evidence or intentional rejection,
deletion/archive commit, rollback path, and next action. The validator rejects
archive/delete commits recorded against pending compatibility surfaces.
