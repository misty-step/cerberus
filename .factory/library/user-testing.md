# User Testing

Validation surface, tools, and resource guidance for user-testing validators.

**What belongs here:** testable user surfaces, validation approach, setup assumptions, resource-cost classification.
**What does NOT belong here:** implementation TODOs or feature decomposition.

---

## Validation Surface

- Surface: terminal-only CLI
- Canonical flow: `cerberus review --repo <path> --base <ref> --head <ref>`
- Validation should use deterministic fixture repos/ref ranges plus deterministic provider doubles
- Required validation artifacts:
  - terminal transcript
  - resolved refs
  - resolved config snapshot/diff
  - planner trace
  - reviewer execution ledger
- No browser, no HTTP API, no Sprite/Fly runtime, no port-binding checks beyond proving nothing was started

## Validation Concurrency

- Machine snapshot used for planning: 11 CPU cores, ~36 GB host RAM, Docker available locally
- Practical validator cost:
  - targeted CLI/config/planner checks: medium
  - package build + end-to-end CLI smoke: medium to high
- Max concurrent validators for this mission: **1**
- Reasoning: package builds, fixture-repo setup, and deterministic double harnesses are lightweight compared with a web app, but this mission is a large structural refactor and its end-to-end CLI/package validation is still heavy enough that serial validation is the safest path

## Current Dry-Run Notes

- Local Elixir/Mix toolchain is present and usable
- Current legacy CLI/release path is not the final target and is partially broken in dry-run mode; that is expected because the mission replaces it
- No long-running validation service is required
