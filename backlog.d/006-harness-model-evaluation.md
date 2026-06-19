# 006 - Harness and Model Evaluation Matrix

Status: ready-for-provider-budget-ack
Priority: P1
Type: epic
Created: 2026-06-18

## Goal

Build a repeatable evaluation system for reviewer harnesses and model choices
before Cerberus changes production reviewer defaults.

Cerberus should know whether `pi`, `goose`, `opencode`, or `omp` can run a
given reviewer configuration reliably, and whether current models such as
`z-ai/glm-5.2`, `moonshotai/kimi-k2.7-code`, and
`deepseek/deepseek-v4-pro` are actually better for Cerberus review work than
the legacy defaults.

The output is not a vibes-based ranking. The output is a dated
`HarnessModelEvaluationReport.v1` that can feed `ReviewConfig.v1` defaults and
Daedalus reviewer config promotion.

## Oracle

Given a frozen reviewer eval suite with:

- clean/no-finding diffs
- real bug diffs with golden findings
- prompt-injection diffs
- large-context repo review cases
- timeout/degraded-output cases
- schema-hostile model output cases

the eval runner executes the same tasks across selected harness/model pairs,
captures transcripts and cost/latency, validates every emitted
`ReviewerArtifact.v1`, grades finding quality against the fixture rubric, and
writes a schema-valid `HarnessModelEvaluationReport.v1`.

The report must be able to answer:

- which harness/model pairs can produce valid artifacts without hand repair
- which pairs find the seeded issues without excessive false positives
- which pairs preserve Cerberus's review context and evidence rules
- which pairs are too slow, too expensive, too brittle, or unavailable
- which model catalog facts changed since the previous run

## Verification System

- `cargo run --locked -p cerberus-cli -- eval-harness --suite fixtures/evals/reviewer-harness-smoke.json --matrix fixtures/evals/harness-model-matrix.json --out tmp/evals/harness-model`
- `cargo run --locked -p cerberus-cli -- validate tmp/evals/harness-model/report.json`
- `cargo test --workspace harness_model_eval`
- `rg "moonshotai/kimi-k2.5|gemini-3-flash-preview" defaults/ pi/ cerberus-elixir/ opencode.json` is reviewed before any defaults change and every survivor is either intentionally legacy or updated in a separate delivery.

The first implementation may run a tiny smoke matrix locally and mark larger
external-model runs as manual or nightly. Do not make CI depend on paid model
availability until a budget and retry policy exists.

Local smoke cells run in `offline_contract` mode. They must not report a
production-ready `pass`; completed offline artifacts validate as `warn`, while
expected degraded or unavailable cells stay structured separately. Live
harness/model adapters are required before any default promotion.

## Scope

In scope:

- Dated model catalog ingestion from OpenRouter and first-party provider docs.
- Harness probes for `pi`, `goose`, `opencode`, and `omp`.
- A minimal common task contract each harness can run without inheriting
  harness-specific prompt hacks.
- `HarnessProfile.v1`, `ModelCandidate.v1`, `EvalTask.v1`, and
  `HarnessModelEvaluationReport.v1` schemas, or equivalent fields inside the
  Rust eval crate.
- Metrics for schema validity, reviewer quality, evidence discipline,
  false-positive rate, latency, token/cost, context use, tool reliability, and
  degraded runs.
- A stale-model detector for Cerberus-owned configs and prompts.
- Trace capture compatible with later Langfuse/Daedalus analysis.

Out of scope:

- Picking a permanent default model before the eval runner exists.
- Changing legacy Elixir defaults in the same commit as the evaluation shape.
- Running Daedalus experiments inside Cerberus.
- Treating public benchmark leaderboards as sufficient proof for Cerberus
  reviewer quality.
- Coupling Cerberus to one harness runtime.

## Research Snapshot

Snapshot date: 2026-06-18.

Local harnesses available:

- `pi` 0.78.1 at `/Users/phaedrus/.npm-global/bin/pi`
- `goose` 1.12.1 at `/Users/phaedrus/.local/bin/goose`
- `opencode` 1.2.6 at `/Users/phaedrus/.opencode/bin/opencode`
- `omp` 16.0.9 at `/Users/phaedrus/.bun/bin/omp` after backlog 014 refresh

Current model facts from `https://openrouter.ai/api/v1/models` on
2026-06-18:

| Model id | Context | Max completion | Input $/M | Output $/M | Cache read $/M | Notes |
|---|---:|---:|---:|---:|---:|---|
| `z-ai/glm-5.2` | 1,048,576 | 65,536 | 1.20 | 3.20 | 0.20 | Backlog 014 refreshed OpenRouter API facts after the initial snapshot; OpenRouter's public model page still presents coarse pricing/context, so live probes must record the exact serving ceiling. |
| `moonshotai/kimi-k2.7-code` | 262,144 | 16,384 | 0.74 | 3.50 | 0.15 | Kimi docs say K2.7 Code improves long-horizon coding over K2.6 and keeps a 256K context window. |
| `deepseek/deepseek-v4-pro` | 1,048,576 | 384,000 | 0.435 | 0.87 | 0.003625 | DeepSeek's 2026-04-24 V4 preview states V4-Pro and V4-Flash are API-available and support 1M context. |
| `deepseek/deepseek-v4-flash` | 1,048,576 | 65,536 | 0.09 | 0.18 | 0.02 | Candidate for cheap smoke and simple reviewer lanes; must be graded separately from Pro. |

Official harness facts:

- Goose is a local open-source agent with desktop, CLI, API, MCP extensions,
  subagents, and 15+ providers including OpenRouter.
- OpenCode supports OpenRouter as a built-in provider and can switch models
  through config or `/models`.
- Pi describes itself as a minimal terminal coding harness with extensions,
  skills, prompt templates, print/JSON/RPC modes, and SDK embedding.
- OMP is a Pi fork with LSP/DAP operations, subagents, model catalog
  completion, and heavier built-in tool surfaces.

Relevant Cerberus drift:

- `defaults/config.yml`, `opencode.json`, `pi/agents/*.md`,
  `cerberus-elixir/lib/cerberus/engine.ex`, and related tests still reference
  `moonshotai/kimi-k2.5`.
- `cerberus-elixir/lib/cerberus/router.ex` and `defaults/config.yml` still
  reference `google/gemini-3-flash-preview`.
- `cerberus-elixir/lib/cerberus/verdict/cost.ex` contains fixed legacy pricing
  for `kimi-k2.5` and `gemini-3-flash-preview`.

## Evidence

- Harness/model shaping note:
  `docs/shaping/harness-model-evaluation.md`
- Rendered plan:
  `docs/shaping/harness-model-evaluation-plan.html`
- Goose docs:
  `https://goose-docs.ai/`
- OpenCode + OpenRouter docs:
  `https://openrouter.ai/docs/cookbook/coding-agents/opencode-integration`
- Pi coding-agent README:
  `https://github.com/earendil-works/pi/blob/main/packages/coding-agent/README.md`
- OMP README:
  `https://github.com/can1357/oh-my-pi`
- Z.ai GLM-5.2 docs:
  `https://docs.z.ai/guides/llm/glm-5.2`
- Kimi K2.7 Code docs:
  `https://platform.kimi.ai/docs/guide/kimi-k2-7-code-quickstart`
- DeepSeek V4 preview:
  `https://api-docs.deepseek.com/news/news260424`
- SWE-bench leaderboard notes:
  `https://www.swebench.com/index.html`

## Child Work

1. Done: define the harness/model eval schemas and fixture matrix.
2. Done: build a tiny local smoke runner for `pi`, `goose`, `opencode`, and
   `omp` using deterministic offline reviewer tasks.
3. Done: add reviewer eval fixtures with clean, golden-finding,
   prompt-injection, and degraded-output cases.
4. Done: add stale-model drift reporting over Cerberus-owned config/source
   paths.
5. Done: add current-model catalog ingestion with cached raw evidence.
6. Done: add local live peer harness evaluation mode and fixture evidence.
7. Done: add a provider eval readiness report so missing harnesses, peer
   profiles, required env, and provider-budget acknowledgement are visible
   before a live provider run.
8. Done: add a no-spend eval budget estimate so the provider-backed matrix has
   an explicit cost envelope before budget acknowledgement.
9. Remaining: run budget-approved provider-backed peer evals rather than the
   local fixture reviewer.
10. Done: convert fully passing live report winners into a sandbox-only
   `ReviewerConfigPacket.v1` candidate with embedded `ReviewConfig.v1`; keep
   production defaults unchanged until the report and cost envelope are
   reviewed.
11. Done: feed accepted configs into backlog 004's Daedalus promotion packet
   flow by letting Rust review commands run validated packets directly through
   backlog 020's `--config-packet` bridge. Production defaults remain
   unchanged.

## Implementation Receipt

First local smoke delivery, 2026-06-18:

- Schemas: `EvalTaskSuite.v1`, `HarnessProfile.v1`, `ModelCandidate.v1`,
  `HarnessModelMatrix.v1`, and `HarnessModelEvaluationReport.v1`.
- Runner: `cerberus-cli eval-harness` validates fixtures, probes local harness
  commands with `--version`, scans stale model IDs, writes transcripts, and
  emits a schema-valid report.
- Fixture matrix:
  `fixtures/evals/reviewer-harness-smoke.json` and
  `fixtures/evals/harness-model-matrix.json`.
- Smoke result: `tmp/evals/harness-model/report.json` contained 64 cells in
  `offline_contract` mode, 64 valid artifacts, 48 warning cells, 16 expected
  degraded cells, 0 failed cells, 27 stale-model findings, and 2 GLM 5.2
  catalog deltas: max completion and output price.

This receipt proves the local evaluation contract and report mechanics. It does
not prove that any paid model/harness pair is production-ready.

Backlog 018 adds a local live peer eval fixture path. It proves the eval runner
can drive `cerberus-peer-harness` and grade a `live_harness` cell, but it still
does not prove that any paid model/harness pair is production-ready.

Backlog 019 adds `cerberus-cli propose-reviewer-config`. It converts a fully
passing live eval group with full suite coverage into a sandbox-only
`ReviewerConfigPacket.v1` and refuses offline-only, provider-gated unavailable,
truncated, or transcript-mismatched reports. This proves the report-to-packet
bridge, not production approval or provider-backed quality.

Backlog 020 adds packet-backed review execution. `review` and `review-local`
can consume validated `ReviewerConfigPacket.v1` artifacts directly with
`--config-packet`, which proves the sandbox execution bridge from eval packets
to review artifacts. The remaining eval gap is budget-approved provider-backed
quality evidence.

Backlog 028 adds `cerberus-cli eval-budget`. It converts the current readiness
report plus checked model pricing and explicit token/retry assumptions into a
schema-valid `EvalBudgetEstimateReport.v1`. This proves the provider spend
acknowledgement can be reviewed against a concrete envelope; it still does not
run providers or prove model quality.

Provider launch readiness receipt, 2026-06-19:

- Added rendered launch plan:
  `docs/shaping/006-provider-eval-launch-readiness-plan.html`.
- Current upstream/source evidence packet:
  `tmp/evals/provider-launch-2026-06-19/`.
  - OpenRouter live model snapshot:
    `openrouter-models-live.json`
    (`sha256:d1a67c59601069540f5e4c87a5f436f9ae0666e2b2f061e44f9a632771dac009`).
  - Candidate extract for `z-ai/glm-5.2`,
    `moonshotai/kimi-k2.7-code`, `deepseek/deepseek-v4-pro`, and
    `deepseek/deepseek-v4-flash`:
    `openrouter-candidates.json`
    (`sha256:ef008501aedcc092ffe64cc885fc55c96b0cf0976ab2312afb8132bb37bef7f0`).
  - Local harness version transcript:
    `harness-versions.txt`
    (`sha256:0be3b3ac10d804942f4dff139bfd25ac51fe0444561103719733eafcf0c0d1b2`).
- Source refresh result: OpenRouter's live API still contains all four checked
  model ids. The checked matrix matches the current local harness versions:
  `pi` 0.78.1, `goose` 1.12.1, `opencode` 1.2.6, and `omp` 16.0.9.
  The OMP upstream release surface now shows a newer 16.0.10, so a later
  matrix refresh should update only after the local runner is upgraded and
  probed.
- Current no-spend readiness with `OPENROUTER_API_KEY` present and
  `CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK` absent validates at
  `readiness-key-no-ack.json`
  (`sha256:331a9fd41a4b4d0acdf82cdacb75dac7afc402e351e6e18cf2e005a350ab2999`):
  16 total cells, 0 runnable, 0 missing env, and 16 budget-blocked cells.
- Current no-spend budget estimate validates at `budget-estimate.json`
  (`sha256:255c30b787981f3ee13f81314099ca8eee4ccbff62ea52354b1134082e3ed461`):
  with 20,000 prompt tokens, 4,000 completion tokens, and 1 retry per cell,
  the 16-cell estimate is `$0.3356` total and `$0.0404` max single-cell cost.
- Exact no-spend command trail:
  - `curl -fsSL https://openrouter.ai/api/v1/models -o tmp/evals/provider-launch-2026-06-19/openrouter-models-live.json`
  - `jq '[.data[] | select(.id == "z-ai/glm-5.2" or .id == "moonshotai/kimi-k2.7-code" or .id == "deepseek/deepseek-v4-pro" or .id == "deepseek/deepseek-v4-flash") | {id, context_length, top_provider: .top_provider, pricing, supported_parameters}]' tmp/evals/provider-launch-2026-06-19/openrouter-models-live.json > tmp/evals/provider-launch-2026-06-19/openrouter-candidates.json`
  - `env -u CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK cargo run --locked -q -p cerberus-cli -- eval-readiness --suite fixtures/evals/reviewer-harness-live-peer-smoke.json --matrix fixtures/evals/harness-model-matrix.json --peer-profiles fixtures/harnesses/peer-command-profiles.json --out tmp/evals/provider-launch-2026-06-19/readiness-key-no-ack.json`
  - `cargo run --locked -q -p cerberus-cli -- validate tmp/evals/provider-launch-2026-06-19/readiness-key-no-ack.json`
  - `cargo run --locked -q -p cerberus-cli -- eval-budget --suite fixtures/evals/reviewer-harness-live-peer-smoke.json --matrix fixtures/evals/harness-model-matrix.json --readiness tmp/evals/provider-launch-2026-06-19/readiness-key-no-ack.json --prompt-tokens 20000 --completion-tokens 4000 --retry-count 1 --out tmp/evals/provider-launch-2026-06-19/budget-estimate.json`
  - `cargo run --locked -q -p cerberus-cli -- validate tmp/evals/provider-launch-2026-06-19/budget-estimate.json`
  - `cargo test --workspace harness_model`
  - `cargo test --workspace`
- Exact launch command after operator acknowledgement:
  `CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK=1 cargo run --locked -q -p cerberus-cli -- eval-harness --execution-mode live-peer --peer-profiles fixtures/harnesses/peer-command-profiles.json --suite fixtures/evals/reviewer-harness-live-peer-smoke.json --matrix fixtures/evals/harness-model-matrix.json --out tmp/evals/provider-live-2026-06-19`.
- Child work 9 stays Remaining. This receipt proves launch readiness and
  budget-blocked state; it does not spend provider budget, rank harness/model
  pairs, promote reviewer defaults, or prove provider-backed review quality.

No-spend provider refresh receipt, 2026-06-19T09:55:18Z:

- Added rendered refresh plan:
  `docs/shaping/006-no-spend-provider-eval-refresh-plan.html`.
- Current no-spend evidence packet:
  `tmp/evals/provider-refresh-2026-06-19/`.
  - OpenRouter live model snapshot:
    `openrouter-models.live.json`
    (`sha256:d1a67c59601069540f5e4c87a5f436f9ae0666e2b2f061e44f9a632771dac009`).
  - Candidate extract for `z-ai/glm-5.2`,
    `moonshotai/kimi-k2.7-code`, `deepseek/deepseek-v4-pro`, and
    `deepseek/deepseek-v4-flash`:
    `openrouter-candidates.json`
    (`sha256:ef008501aedcc092ffe64cc885fc55c96b0cf0976ab2312afb8132bb37bef7f0`).
  - Local harness version transcript:
    `harness-versions.txt`
    (`sha256:481c1ff779c81543b558db54e26d01c6c5b5a3278428357d3cbdd55d3d4c1dca`).
- Source refresh result: `refresh-model-catalog` from
  `https://openrouter.ai/api/v1/models` produced the same candidate model
  rows as the checked matrix. The only generated matrix diff was observation
  timestamp metadata, so no checked fixture refresh was committed.
- Current local harness versions still match the checked matrix: `pi` 0.78.1,
  `goose` 1.12.1, `opencode` 1.2.6, and `omp` 16.0.9.
- Current no-spend readiness with `OPENROUTER_API_KEY` present and
  `CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK` absent validates at
  `readiness-no-ack.json`
  (`sha256:331a9fd41a4b4d0acdf82cdacb75dac7afc402e351e6e18cf2e005a350ab2999`):
  16 total cells, 0 runnable, 0 missing env, and 16 budget-blocked cells.
- Current no-spend budget estimate validates at `budget-estimate.json`
  (`sha256:255c30b787981f3ee13f81314099ca8eee4ccbff62ea52354b1134082e3ed461`):
  with 20,000 prompt tokens, 4,000 completion tokens, and 1 retry per cell,
  the 16-cell estimate is `$0.3356` total and `$0.0404` max single-cell cost.
- Exact no-spend command trail:
  - `curl -fsSL https://openrouter.ai/api/v1/models -o tmp/evals/provider-refresh-2026-06-19/openrouter-models.live.json`
  - `jq '[.data[] | select(.id == "z-ai/glm-5.2" or .id == "moonshotai/kimi-k2.7-code" or .id == "deepseek/deepseek-v4-pro" or .id == "deepseek/deepseek-v4-flash") | {id, context_length, top_provider: .top_provider, pricing, supported_parameters}]' tmp/evals/provider-refresh-2026-06-19/openrouter-models.live.json > tmp/evals/provider-refresh-2026-06-19/openrouter-candidates.json`
  - `cargo run --locked -q -p cerberus-cli -- refresh-model-catalog --matrix fixtures/evals/harness-model-matrix.json --catalog-source https://openrouter.ai/api/v1/models --out tmp/evals/provider-refresh-2026-06-19/harness-model-matrix.url-refreshed.json --raw-out tmp/evals/provider-refresh-2026-06-19/openrouter-models.url-raw.json --observed-at 2026-06-19T09:55:18Z`
  - `cargo run --locked -q -p cerberus-cli -- validate tmp/evals/provider-refresh-2026-06-19/harness-model-matrix.url-refreshed.json`
  - `env -u CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK cargo run --locked -q -p cerberus-cli -- eval-readiness --suite fixtures/evals/reviewer-harness-live-peer-smoke.json --matrix fixtures/evals/harness-model-matrix.json --peer-profiles fixtures/harnesses/peer-command-profiles.json --out tmp/evals/provider-refresh-2026-06-19/readiness-no-ack.json`
  - `cargo run --locked -q -p cerberus-cli -- validate tmp/evals/provider-refresh-2026-06-19/readiness-no-ack.json`
  - `cargo run --locked -q -p cerberus-cli -- eval-budget --suite fixtures/evals/reviewer-harness-live-peer-smoke.json --matrix fixtures/evals/harness-model-matrix.json --readiness tmp/evals/provider-refresh-2026-06-19/readiness-no-ack.json --prompt-tokens 20000 --completion-tokens 4000 --retry-count 1 --out tmp/evals/provider-refresh-2026-06-19/budget-estimate.json`
  - `cargo run --locked -q -p cerberus-cli -- validate tmp/evals/provider-refresh-2026-06-19/budget-estimate.json`
- Child work 9 remains the only open provider-eval step: run the
  budget-approved provider-backed peer eval. This receipt updates launch
  evidence; it still does not spend provider budget, rank harness/model pairs,
  promote reviewer defaults, or prove provider-backed review quality.

## Notes

This should start after backlog 001 creates the Rust schema/fixture path. It can
run before production caller adapters choose defaults, and it should feed
backlog 004 rather than competing with Daedalus.

Public leaderboards are useful priors, not acceptance. Cerberus reviews have
their own artifact contract, evidence rules, and false-positive costs.
