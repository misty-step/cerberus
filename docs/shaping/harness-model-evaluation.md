# Harness and Model Evaluation Shape

Date: 2026-06-19
Status: local live-peer fixture implemented

## Goal

Research and shape how Cerberus should evaluate agent harnesses and current
coding/review models before changing reviewer defaults.

The operator outcome is simple: Cerberus should promote reviewer configurations
because they produce better review artifacts in Cerberus's own eval loop, not
because a public leaderboard or model announcement looks strong.

## Premise

Cerberus is being reshaped into a Rust review-artifact core. That makes model
and harness selection part of the product contract:

```text
ReviewRequest.v1 + ReviewConfig.v1
  -> reviewer harness + model execution
  -> ReviewerArtifact.v1
  -> ReviewRunArtifact.v1
```

The current repo still has older model defaults (`kimi-k2.5`,
`gemini-3-flash-preview`) and fixed cost assumptions. Those may remain correct
for the legacy Elixir compatibility path, but they should not become the Rust
engine's defaults without a dated evaluation loop.

## Current Local Evidence

Commands run on 2026-06-18:

```sh
command -v pi goose opencode omp
pi --version
goose --version
opencode --version
omp --version
rg -n "moonshotai/kimi-k2\\.5|gemini-3-flash-preview|openrouter/" cerberus-elixir defaults pi opencode.json
python3 - <<'PY'
import json, urllib.request
data=json.load(urllib.request.urlopen("https://openrouter.ai/api/v1/models"))["data"]
for term in ["kimi-k2.7-code","deepseek-v4","glm-5.2"]:
    print([m["id"] for m in data if term in m["id"]])
PY
```

Local harnesses:

| Harness | Version | Path | Evaluation implication |
|---|---:|---|---|
| Pi | 0.78.1 | `/Users/phaedrus/.npm-global/bin/pi` | Minimal, extensible baseline; likely the cleanest way to test Cerberus-owned prompt/context discipline. |
| Goose | 1.12.1 | `/Users/phaedrus/.local/bin/goose` | Rich local agent with MCP/subagent surface; must be tested for prompt isolation and artifact discipline. |
| OpenCode | 1.2.6 | `/Users/phaedrus/.opencode/bin/opencode` | Strong provider/config support; repo already has `opencode.json`, so it is a practical candidate for local review runs. |
| OMP | 16.0.9 | `/Users/phaedrus/.bun/bin/omp` | Heavier Pi-derived harness with LSP/DAP/subagents; promising but needs strict control so harness power does not mask model weakness. |

Local model drift:

- `defaults/config.yml` defaults to `openrouter/moonshotai/kimi-k2.5`.
- `opencode.json` uses `openrouter/moonshotai/kimi-k2.5`.
- `pi/agents/*.md` pin `openrouter/moonshotai/kimi-k2.5`.
- `cerberus-elixir/lib/cerberus/engine.ex` and `cli.ex` default to
  `openrouter/moonshotai/kimi-k2.5`.
- `cerberus-elixir/lib/cerberus/router.ex` defaults routing to
  `openrouter/google/gemini-3-flash-preview`.
- `cerberus-elixir/lib/cerberus/verdict/cost.ex` has fixed rates for older
  models.

## Current External Evidence

Firecrawl search was attempted in this session, but the account returned HTTP
402. Web retrieval therefore fell back to built-in search and direct
provider/API requests.

Primary-source harness facts:

| Harness | Source | Evidence used |
|---|---|---|
| Goose | `https://goose-docs.ai/` | Goose is open source, local, supports desktop/CLI/API, MCP extensions, subagents, and 15+ providers including OpenRouter. |
| OpenCode | `https://openrouter.ai/docs/cookbook/coding-agents/opencode-integration` and `https://opencode.ai/docs/providers/` | OpenCode supports OpenRouter, model switching, provider routing, and 75+ providers through its provider system. |
| Pi | `https://github.com/earendil-works/pi/blob/main/packages/coding-agent/README.md` | Pi describes itself as a minimal terminal coding harness with extensions, skills, prompt templates, print/JSON/RPC modes, and SDK embedding. |
| OMP | `https://github.com/can1357/oh-my-pi` | OMP is a Pi fork with LSP/DAP operations, subagents, hashline edits, model catalog completion, and a broad built-in tool surface. |

Primary-source model facts:

| Model | Source | Evidence used |
|---|---|---|
| `z-ai/glm-5.2` | `https://docs.z.ai/guides/llm/glm-5.2` and OpenRouter API | Z.ai describes GLM-5.2 as a 1M-context long-horizon coding model with function calling, structured output, context caching, and 128K max output. OpenRouter lists 1,048,576 context and different top-provider output limits, so live probes must reconcile the exact ceiling. |
| `moonshotai/kimi-k2.7-code` | `https://platform.kimi.ai/docs/guide/kimi-k2-7-code-quickstart` and OpenRouter API | Kimi docs say K2.7 Code improves long-horizon coding and agentic capabilities over K2.6, reduces overthinking, and keeps a 256K context window. OpenRouter lists the model with text/image input, tool parameters, and structured output support. |
| `deepseek/deepseek-v4-pro` / `deepseek-v4-flash` | `https://api-docs.deepseek.com/news/news260424` and OpenRouter API | DeepSeek's V4 preview says V4-Pro and V4-Flash are API-available, support 1M context, integrate with agents including OpenCode, and distinguish Pro from Flash by capability/cost profile. |
| SWE-bench | `https://www.swebench.com/index.html` | SWE-bench Verified is useful as an external prior, but it measures patch-resolution systems and does not replace Cerberus's reviewer-artifact eval. |

OpenRouter API snapshot, 2026-06-18:

| Model id | Context | Max completion | Input $/M | Output $/M | Cache read $/M | Supported params of interest |
|---|---:|---:|---:|---:|---:|---|
| `z-ai/glm-5.2` | 1,048,576 | 65,536 | 1.20 | 3.20 | 0.20 | tools, tool_choice, structured_outputs, reasoning, response_format |
| `moonshotai/kimi-k2.7-code` | 262,144 | 16,384 | 0.74 | 3.50 | 0.15 | tools, tool_choice, structured_outputs, reasoning, response_format |
| `deepseek/deepseek-v4-pro` | 1,048,576 | 384,000 | 0.435 | 0.87 | 0.003625 | tools, tool_choice, structured_outputs, reasoning, response_format |
| `deepseek/deepseek-v4-flash` | 1,048,576 | 65,536 | 0.09 | 0.18 | 0.02 | tools, tool_choice, structured_outputs, reasoning, response_format |

## Recommended Shape

Add backlog 006 as the evaluation bridge between the Rust contract spine and
Daedalus reviewer promotion.

```text
fixtures/evals/reviewer-harness-*.json
  -> cerberus-cli eval-harness
  -> HarnessModelEvaluationReport.v1
  -> ReviewConfig.v1 candidate
  -> Daedalus ReviewerConfigPacket.v1 promotion path
```

The evaluation should be matrix-shaped:

```text
harnesses = pi, goose, opencode, omp
models = glm-5.2, kimi-k2.7-code, deepseek-v4-pro, deepseek-v4-flash
tasks = clean, seeded-bug, injection, long-context, degraded, schema-hostile
```

Each cell runs the same task contract and emits:

- transcript and raw provider/harness metadata
- parsed `ReviewerArtifact.v1`
- schema-validity result
- golden-finding score
- false-positive score
- evidence-discipline score
- latency and token/cost metrics
- context-size and truncation notes
- degraded/crash reason

## Implemented Smoke Surface

Backlog 006 now has a Rust-side offline smoke runner:

- `cerberus-schema` defines `EvalTaskSuite.v1`, `HarnessProfile.v1`,
  `ModelCandidate.v1`, `HarnessModelMatrix.v1`, and
  `HarnessModelEvaluationReport.v1`.
- `cerberus-core` grades checked-in eval tasks against exact fixture findings,
  records schema validity, structured unavailable/degraded states, estimated
  cost, catalog deltas, and report summaries.
- `cerberus-cli eval-harness` probes local harness commands with `--version`,
  scans configured source paths for stale model IDs, writes transcripts, and
  emits `tmp/evals/harness-model/report.json`.
- `cerberus-cli refresh-model-catalog` ingests an OpenRouter-compatible raw
  catalog from a file or URL, caches the exact raw JSON, and emits a refreshed
  schema-valid matrix before the eval run.
- `fixtures/evals/reviewer-harness-smoke.json` covers clean/no-finding,
  seeded finding, prompt-injection text, and degraded timeout cases.
- `fixtures/evals/harness-model-matrix.json` captures the 2026-06-18 local
  harness versions and OpenRouter model facts used by this run.

Backlog 014 refreshed this checked matrix later on 2026-06-18 after live
OpenRouter API and local harness probes showed drift: OMP moved to `16.0.9`, and
GLM 5.2's current OpenRouter row reports max completion `65,536` and output
price `$3.20/M` while preserving the earlier `16,384` / `$4.20/M` matrix values
as the previous snapshot.

Backlog 018 adds `cerberus-cli eval-harness --execution-mode live-peer` with
`--peer-profiles <PeerHarnessCommandProfiles.v3.json>`. The CLI drives
`cerberus-peer-harness` live, writes per-cell input, artifact, transcript, and
execution-plan files, then asks `cerberus-core` to grade the resulting
`ReviewerArtifact.v1`. The checked local fixture matrix proves one
`live_harness` pass cell without provider spend. Provider-backed Pi, Goose,
OpenCode, and OMP cells still fail closed as `unavailable` unless provider
budget acknowledgement and required credentials are present.

The current smoke result is intentionally not a live model bake-off. Cells run
in `offline_contract` mode and must validate as `warn` or structured
degraded/unavailable outcomes, not as production-ready `pass` outcomes. This
proves the evaluation contract, report validation, stale-model drift reporting,
and degraded/unavailable cell handling. Paid harness/model execution remains a
later adapter step before any production defaults change.

## Alternatives Considered

### Public Leaderboards Only

Rejected. SWE-bench and Terminal-Bench style leaderboards are useful priors,
but Cerberus review quality depends on artifact validity, evidence discipline,
false-positive behavior, and reviewer panel diversity.

### Daedalus Owns All Evaluation

Rejected as the first step. Daedalus should own the broader foundry and
promotion loop, but Cerberus needs local contract fixtures first so Daedalus has
a clear artifact target to export into.

### Update Model Defaults Immediately

Rejected. Current providers show newer candidates, but Cerberus still needs
harness-level smoke evidence, schema validity, cost accounting, and false
positive measurements before replacing legacy defaults.

### One Harness Winner

Rejected. Harnesses fail differently. Pi may be best for minimal prompt/context
discipline, OpenCode for provider configuration, Goose for MCP/subagent
capabilities, and OMP for IDE-native tool surfaces. The matrix should measure
role fit instead of forcing one global winner.

## Oracle

The first accepted delivery creates a tiny but real matrix runner:

```sh
cargo run --locked -p cerberus-cli -- eval-harness \
  --suite fixtures/evals/reviewer-harness-smoke.json \
  --matrix fixtures/evals/harness-model-matrix.json \
  --out tmp/evals/harness-model

cargo run --locked -p cerberus-cli -- validate \
  tmp/evals/harness-model/report.json

cargo test --workspace harness_model_eval
```

Local smoke acceptance requires each locally installed harness profile to be
probed and each matrix cell to emit either a schema-valid offline
`ReviewerArtifact.v1` in `warn` status or a structured degraded/unavailable
record. Local live-peer acceptance requires at least one task to run through
`cerberus-peer-harness` with a captured transcript and `live_harness` report
cell. Paid external model cells may be marked manual/nightly until budget and
retry policy exist.

## Verification System

- Claim: Cerberus can evaluate harness/model pairs for reviewer artifact quality
  before changing defaults.
- Falsifier: a model can be promoted without a schema-valid artifact, transcript,
  cost/latency record, and held-out finding-quality grade.
- Driver: `cerberus-cli eval-harness` over a checked-in suite and matrix.
- Grader: JSON schema validation, deterministic fixture assertions, rubric
  grades for seeded findings, false-positive thresholds, and budget limits.
- Evidence packet: `tmp/evals/harness-model/report.json`, transcripts, raw model
  catalog snapshot, and rendered summary.
- Cadence: local smoke before config changes; full matrix before model
  promotion; periodic refresh when provider catalogs drift.
- Gaps / waiver: no production model default changes in this shaping pass.

## Stop Conditions

- Stop if the Rust contract spine from backlog 001 does not yet define the
  `ReviewerArtifact.v1` fields needed for grading.
- Stop if a harness requires prompt or tool privileges that would make the same
  task unfair across other harnesses.
- Stop if provider pricing, context, or output limits conflict and no live probe
  records which value applies to the target platform.
- Stop if a public benchmark result is being treated as the only proof.

## Links

- Backlog ticket: `backlog.d/006-harness-model-evaluation.md`
- HTML plan: `docs/shaping/harness-model-evaluation-plan.html`
- Rust contract ticket: `backlog.d/001-rust-review-engine-contract.md`
- Daedalus promotion ticket: `backlog.d/004-daedalus-reviewer-config-promotion.md`
