# Rust Review Engine Resurrection

Date: 2026-06-18
Status: shaped

## Goal

Resurrect Cerberus as a Rust review engine and artifact contract that can be
used by multiple independent callers.

The core job is not "review a GitHub pull request." The core job is:

```text
review this change under this policy and return a structured artifact
```

GitHub pull requests remain the first and most important adapter, but pull
request semantics should not leak into the core engine.

## Assumptions

- Rust is the long-term implementation language for durable Cerberus code.
- The legacy Elixir engine is donor material and compatibility surface.
- ThinkTank should be decommissioned as a separate review engine after its useful
  bench artifacts are migrated.
- Bitterblossom and Olympus are independent sibling callers. They may both call
  Cerberus; neither should know about the other.
- Daedalus is the evaluation and promotion bench for reviewer configurations.

## Current Evidence

| Surface | Evidence | Implication |
|---|---|---|
| Cerberus action/API | `README.md` and `docs/api-contract.md` describe a thin GitHub action dispatching to an API. | Preserve the dispatch/poll shape as a GitHub compatibility adapter, not as the core ontology. |
| Review-run boundary | `docs/adr/004-review-execution-boundary.md` accepts a provider-agnostic review-run contract. | The Rust rewrite should make this contract real and versioned. |
| Legacy engine core | `cerberus-elixir/lib/cerberus/engine.ex` takes diff/context, routes a panel, runs reviewers, and aggregates. | This is the module-depth donor: port behavior, not framework shape. |
| Aggregation | `cerberus-elixir/lib/cerberus/verdict/aggregator.ex` handles confidence gating, dedupe, cost, reserves, and overrides. | These semantics belong in the Rust core after fixture proof. |
| Bitterblossom | `/Users/phaedrus/Development/bitterblossom/project.md` defines an event plane with task/agent/trigger/run primitives. | Do not move queueing, ledgers, recurring triggers, or budgets into Cerberus. |
| Olympus Argus | `/Users/phaedrus/Development/adminifi/olympus/orchestrator/src/argus-review-poster.ts` validates untrusted artifacts and owns stale-head/marker/posting policy. | Keep Adminifi posting policy in Olympus; Cerberus emits artifacts/projections. |
| ThinkTank | `/Users/phaedrus/Development/thinktank/README.md` defines a thin bench launcher with review artifacts. | Migrate artifacts and bench lessons, but avoid a runtime dependency. |
| Daedalus | `/Users/phaedrus/Development/daedalus/DESIGN.md` owns specify/lab/contract stages and replaceable deploy/observe stages. | Daedalus should export measured reviewer configs; Cerberus should import them. |

## Boundary

```text
Bitterblossom task runtime  \
                           -> Cerberus Rust review contract -> ReviewRunArtifact
Olympus Argus dispatcher    /

Daedalus -> measured reviewer config packet -> Cerberus
ThinkTank -> migration inventory -> Cerberus, then decommission review-engine role
```

Cerberus owns:

- review request/config schemas
- reviewer roster/config loading
- routing and reviewer panel selection
- reviewer execution harness abstraction
- per-reviewer artifacts
- aggregation, dedupe, coverage/degrade policy, costs, and overrides
- artifact renderers and adapter SDKs

Cerberus does not own:

- HTTP lifecycle, async queueing, hosted deployment, or service orchestration in
  the core crate
- Bitterblossom's event plane, queue, ledger, retries, budgets, or trigger model
- Olympus's activation gates, stale-head suppression, marker dedupe, or GitHub
  posting authority
- Daedalus experiments, holdouts, scoring, or promotion decisions
- ThinkTank as a runtime dependency for normal review execution

## Contract Sketch

```text
ReviewRequest.v1
  source: local_diff | git_range | github_pr | fixture | external
  change: base, head, files, diff, metadata
  context: title, description, acceptance, linked artifacts
  caller: name, run_id, policy, budget
  render_targets: markdown | github_review | json

ReviewConfig.v1
  reviewers, routing policy, model/provider/harness slots, cost limits,
  coverage/degrade policy, renderer policy

ReviewerArtifact.v1
  reviewer identity, perspective, model/provider/harness, findings, confidence,
  coverage, degraded reason, token/cost, raw transcript pointer

ReviewRunArtifact.v1
  request digest, config digest, verdict, summary, findings, dedupe groups,
  reviewer artifacts, coverage, degraded state, costs, render projections
```

## Backlog Diff

Applied backlog tickets:

- `backlog.d/001-rust-review-engine-contract.md`
- `backlog.d/002-independent-caller-adapters.md`
- `backlog.d/003-thinktank-decommission-migration.md`
- `backlog.d/004-daedalus-reviewer-config-promotion.md`
- `backlog.d/005-legacy-surface-retirement.md`
- `backlog.d/006-harness-model-evaluation.md`

## Sequence

Now:

- Build Rust schemas, fixtures, validator, fake-runner, and renderer.
- Freeze legacy donor behavior behind fixture expectations.
- Shape the harness/model evaluation loop before changing reviewer defaults.

Next:

- Add harness/model eval fixtures for Pi, Goose, OpenCode, OMP, and current
  candidate coding models.
- Add caller fixtures for Bitterblossom and Olympus.
- Add ThinkTank artifact migration inventory.

Later:

- Add live LLM reviewer execution.
- Add Daedalus reviewer config import from measured eval packets.
- Retire Elixir after parity and caller migration.

Blocked:

- Remote repository is still archived; unarchiving/push policy is outside this
  local shaping pass.

## Stop Conditions

- Stop adding adapter work if `ReviewRequest -> ReviewRunArtifact` is not
  proven locally.
- Stop deleting legacy code if there is no Rust parity fixture.
- Stop integrating callers if the integration requires Bitterblossom or Olympus
  to import from each other.
