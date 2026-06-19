# 006 - Harness and Model Evaluation Matrix

Status: implemented-local-smoke
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
7. Remaining: run budget-approved provider-backed peer evals rather than the
   local fixture reviewer.
8. Remaining: convert report winners into a candidate `ReviewConfig.v1`; keep
   production defaults unchanged until the report and cost envelope are
   reviewed.
9. Remaining: feed accepted configs into backlog 004's Daedalus promotion
   packet flow.

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

## Notes

This should start after backlog 001 creates the Rust schema/fixture path. It can
run before production caller adapters choose defaults, and it should feed
backlog 004 rather than competing with Daedalus.

Public leaderboards are useful priors, not acceptance. Cerberus reviews have
their own artifact contract, evidence rules, and false-positive costs.
