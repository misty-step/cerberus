# ThinkTank Review Migration Inventory

Snapshot date: 2026-06-18.

ThinkTank is historical donor material for Cerberus review execution. Cerberus
may import frozen historical review runs for migration and evaluation, but
production review execution must not invoke the `thinktank` CLI or depend on
ThinkTank's runtime directory layout.

## Frozen Run

Representative source:
`/Users/phaedrus/Development/thinktank/tmp/review-pr-289`

Checked migration fixture:
`fixtures/thinktank/review-pr-289/historical-run.json`

Converted Cerberus artifact:
`fixtures/thinktank/review-pr-289/review-run-artifact.json`

The source run used `review/default`, completed on 2026-04-14, and had two
completed reviewer artifacts (`trace`, `scout`) plus one timed-out reviewer
(`proof`). The run predates checked `review/coverage.json` and
`review/degrade_policy.json` artifacts, so those are represented explicitly as
missing historical inputs rather than inferred as successful coverage.

## Artifact Mapping

| ThinkTank artifact or concept | Cerberus destination | Decision |
|---|---|---|
| `manifest.json` run id, bench, status, timing, version | `ReviewRequest.context.metadata`, `ReviewRunArtifact.run_id`, `ReviewRunArtifact.degraded`, `ReviewRunArtifact.reserves`, `CostSummary` | Port. Manifest is durable replay metadata. Unknown usage/cost is represented as zero-cost historical replay, not production cost evidence. |
| `manifest.json` planned agents | `ReviewConfig.reviewers` | Port. Agent ids become reviewer ids; planner perspectives become reviewer perspectives; provider/model is preserved in the model string for historical provenance. |
| `manifest.json` agent status and timeout error | `ReviewerArtifact.status`, `ReviewerArtifact.verdict`, `ReviewerArtifact.degraded_reason` | Port. Exact status protocol maps `ok` to `completed` and `error` plus `timeout` to `timeout`/`SKIP`. |
| `review/context.json` git range and head sha | `ReviewRequest.change`, `ReviewRunArtifact.reviewed_head_sha` | Port. The converted artifact binds to the historical head sha. |
| `review/context.json` changed files and line stats | `ReviewRequest.change.files`, `ReviewRequest.context.metadata` | Port. The compact fixture keeps file paths/statuses and aggregate line stats; it does not need the full historical diff. |
| `review/context.json` change signals | `ReviewRequest.context.metadata` | Port as explicit metadata. Signals are replay context, not review judgment. |
| `review/plan.json` selected agents and briefs | `ReviewConfig.reviewers`, `ReviewRequest.context.metadata` | Port. Briefs inform migration inventory and reviewer configuration; they do not become semantic findings. |
| `review/plan.json` synthesis brief and warnings | `ReviewRequest.context.metadata` | Port. These are route-plan context and risk notes. |
| `agents/*.md` completed reviewer summaries | `ReviewerArtifact.summary`, `ReviewerArtifact.verdict` | Port only from controlled fixture fields. The importer does not parse free-form prose to invent findings. |
| `agents/*.md` timed-out reviewer output | `ReviewerArtifact.status = timeout`, `ReviewerArtifact.verdict = SKIP`, `ReserveSignal::DegradedReviewer` | Port. Timeout is an explicit degraded reviewer state. |
| `review/coverage.json` | Future Cerberus coverage/degraded policy fields | Conditionally port when present. The frozen run predates this artifact, so importer records it in `missing_artifacts`. |
| `review/degrade_policy.json` | `ReviewRunArtifact.degraded`, `ReviewRunArtifact.reserves`, reviewer degraded reasons | Conditionally port when present. The frozen run predates this artifact; no synthetic policy is inferred. |
| `contract.json` bench input | `ReviewRequest.context.summary` and metadata | Port narrow fields only. The migration fixture stores the review task, base/head, and no-synthesis context through public request fields. |
| `trace/events.jsonl` and `trace/summary.json` | Daedalus/eval provenance, not core review artifact | Reject from core. Trace files may be useful for offline eval replay, but they are not required for `ReviewRunArtifact.v1`. |
| `prompts/*.md` | None | Reject. Prompt text is historical execution detail, not a Cerberus runtime dependency. |
| `pi-home/*/auth.json` | None | Reject. Auth homes are runtime state and must not be checked into Cerberus. |
| ThinkTank CLI launch, sandboxing, timeout orchestration | None in `cerberus-core` | Reject. Cerberus may run in local, GitHub Actions, Sprites, or other harnesses without ThinkTank. |
| ThinkTank review/default bench config | Future Cerberus reviewer roster defaults and eval seeds | Donor only. Useful concepts feed Cerberus-owned `ReviewConfig.v1` and Daedalus promotion, not a runtime shell-out. |

## Verification

Local replay and decommission guard:

```sh
cargo test --workspace thinktank_migration
cargo run --locked -p cerberus-cli -- validate fixtures/thinktank/review-pr-289/review-run-artifact.json
rg -n "thinktank" crates/
```

The only allowed Rust references are the compatibility importer module and its
export in `crates/cerberus-adapter`.
