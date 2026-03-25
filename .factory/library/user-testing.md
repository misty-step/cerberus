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

## Flow Validator Guidance: terminal-cli

- Isolation boundary: terminal-only validation against repo-local Mix commands plus unique temp fixture repos under `$(mktemp -d)` or `System.tmp_dir!()`. Do not reuse another validator's temp repo, worktree, or evidence directory.
- Current product root for `cli-core` is `/Users/phaedrus/Development/cerberus-mono/cerberus/cerberus-elixir`; run Mix commands there until the later root-lift milestone changes the app root.
- Prefer `mix run --no-start --no-compile` when invoking `Cerberus.CLI.main/2` directly so the command stays CLI-only and does not boot the app supervisor or start Bandit unnecessarily.
- Deterministic review execution is allowed through the existing CLI runtime override surface (`Application.put_env(:cerberus_elixir, :cli_overrides, ...)`) so validators can inject fixed `call_llm`, `router_call_llm`, `routing_result`, and `config_overrides` values without making live provider calls.
- When invoking repeated deterministic CLI runs in one validation session, give each run unique `config_name`, `router_name`, `review_supervisor_name`, and `task_supervisor_name` values inside `:cli_overrides` to avoid cross-run process-name collisions.
- Capture terminal transcripts, resolved refs, config snapshots/diffs, planner/reviewer ledgers, and git before/after state as files under `.factory/validation/<milestone>/user-testing/flows/` plus the assigned mission evidence directory.
- Validation concurrency for this surface remains `1`; run assertion groups serially.
