# Harness and Model Evaluation Shape

Date: 2026-06-19
Status: provider-backed live smoke captured; default promotion blocked

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

Commands run on 2026-06-19:

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

OpenRouter API snapshot, 2026-06-19:

| Model id | Context | Max completion | Input $/M | Output $/M | Cache read $/M | Supported params of interest |
|---|---:|---:|---:|---:|---:|---|
| `z-ai/glm-5.2` | 1,048,576 | 131,072 | 1.20 | 4.10 | 0.20 | tools, tool_choice, structured_outputs, reasoning, response_format |
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
- `fixtures/evals/harness-model-matrix.json` captures the 2026-06-19 local
  harness versions and OpenRouter model facts used by this run.

Backlog 022 refreshed this checked matrix on 2026-06-19 after live OpenRouter
API probes showed GLM 5.2 drift again: max completion moved from `65,536` to
`131,072`, top-provider context moved from `202,752` to `1,048,576`, and output
price moved from `$3.20/M` to `$4.10/M`. Those 2026-06-18 facts remain preserved
as the previous snapshot.

Backlog 018 adds `cerberus-cli eval-harness --execution-mode live-peer` with
`--peer-profiles <PeerHarnessCommandProfiles.v3.json>`. The CLI drives
`cerberus-peer-harness` live, writes per-cell input, artifact, transcript, and
execution-plan files, then asks `cerberus-core` to grade the resulting
`ReviewerArtifact.v1`. The checked local fixture matrix proves one
`live_harness` pass cell without provider spend. Provider-backed Pi, Goose,
OpenCode, and OMP cells still fail closed as `unavailable` unless provider
budget acknowledgement and required credentials are present.

Backlog 019 adds `cerberus-cli propose-reviewer-config`. The command reads a
`HarnessModelEvaluationReport.v1` plus its matrix, suite, and eval evidence
directory, refuses weak, truncated, or transcript-mismatched reports, and emits
a sandbox-only `ReviewerConfigPacket.v1` only when a harness/model group fully
passes live eval cells for the suite. The generated packet feeds
`validate-reviewer-config` and `import-reviewer-config --dry-run`; it does not
approve production import or mutate defaults.

Backlog 027 adds `cerberus-cli eval-readiness`. The command writes a
schema-valid `EvalReadinessReport.v1` before a provider-backed live-peer eval
run. It probes configured harness commands, joins the checked matrix to peer
harness profiles, probes the live peer runner, records missing required
environment variables, and records whether
`CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK` is present. It does not run provider
harnesses, spend budget, rank models, or promote defaults.

Backlog 028 adds `cerberus-cli eval-budget`. The command reads the checked eval
suite, matrix, and readiness report plus explicit prompt-token,
completion-token, and retry-count assumptions, then writes a schema-valid
`EvalBudgetEstimateReport.v1`. The report exposes a cost envelope for cells
that are ready except for provider budget acknowledgement. It does not estimate
quality, infer real token usage, invoke providers, or change defaults.

No-spend refresh at `2026-06-19T09:55:18Z` captured a fresh OpenRouter API
snapshot and local harness version transcript under
`tmp/evals/provider-refresh-2026-06-19/`. The four checked candidate model rows
matched the current matrix; the generated refresh changed only observation
timestamps, so the checked matrix was not rewritten. Readiness still reports 16
total cells, 0 runnable cells, 0 missing-env cells, and 16 cells blocked only by
missing `CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK`; the budget estimate remains
`$0.3356` total with the documented 20,000 prompt / 4,000 completion token
assumption and one retry.

Provider-backed live smoke ran on 2026-06-19 with explicit budget
acknowledgement:

```sh
PATH="$PWD/target/debug:$PATH" \
CERBERUS_PEER_HARNESS_PROVIDER_BUDGET_ACK=1 \
cargo run --locked -q -p cerberus-cli -- eval-harness \
  --execution-mode live-peer \
  --peer-profiles fixtures/harnesses/peer-command-profiles.json \
  --suite fixtures/evals/reviewer-harness-live-peer-smoke.json \
  --matrix fixtures/evals/harness-model-matrix.json \
  --out tmp/evals/provider-live-2026-06-19-active

cargo run --locked -q -p cerberus-cli -- validate \
  tmp/evals/provider-live-2026-06-19-active/report.json
```

The validated report at
`tmp/evals/provider-live-2026-06-19-active/report.json`
(`sha256:44d341b51413460530d046b5d51511d04612225ce1dad17e4da436115c39c9f4`)
contains 16 cells: 3 valid artifacts, 13 unavailable cells, 0 degraded cells,
0 failed cells, 27 stale-model findings, and average score `0.1875`.

Passing provider-backed live smoke cells:

| Harness | Model | Score | Latency | Estimated cost | Result |
|---|---|---:|---:|---:|---|
| `goose` | `z-ai/glm-5.2` | 1.0 | 25,019 ms | `$0.001242` | Valid `ReviewerArtifact.v1` |
| `goose` | `deepseek/deepseek-v4-pro` | 1.0 | 40,430 ms | `$0.0032` | Valid `ReviewerArtifact.v1` |
| `goose` | `deepseek/deepseek-v4-flash` | 1.0 | 74,610 ms | `$0.0012` | Valid `ReviewerArtifact.v1` |

Unavailable or malformed provider rows:

- `pi` failed across all four models because local extensions hit stale context
  errors or stdout exceeded the peer-runner cap.
- `goose` + `moonshotai/kimi-k2.7-code` produced malformed artifact JSON
  missing `files_with_findings`.
- `opencode` failed across all four models because the current peer profile
  passes the reviewer prompt in a shape OpenCode interprets as a file path.
- `omp` failed across all four models because output either exceeded the cap or
  repeated artifact markers hundreds of times.

The current live result is a one-task profile smoke, not a production model
ranking. It proves that the checked Goose profile can produce valid
provider-backed Cerberus reviewer artifacts for three candidate models in the
checked smoke. It does not prove seeded finding quality, prompt-injection
resistance, long-context behavior, degraded behavior, or schema-hostile output
handling, so production defaults stay unchanged.

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
cell. Candidate config acceptance requires the generated packet to validate and
dry-run through the existing import path while still rejecting production import
without approval. Provider readiness acceptance requires `cerberus-cli
eval-readiness` to write a schema-valid report that names runnable cells and
blockers for missing harnesses, live peer runners, profiles, required env, and
provider-budget acknowledgement before any provider spend. Budget acceptance
requires `cerberus-cli eval-budget` to write a schema-valid cost estimate from
explicit token and retry assumptions before an operator acknowledges provider
spend. Paid external model cells may be marked manual/nightly until budget and
retry policy are approved.

## Verification System

- Claim: Cerberus can evaluate harness/model pairs for reviewer artifact quality
  before changing defaults.
- Falsifier: a model can be promoted without a schema-valid artifact, transcript,
  cost/latency record, and held-out finding-quality grade.
- Driver: `cerberus-cli eval-readiness`, then `cerberus-cli eval-budget`,
  before provider runs; `cerberus-cli eval-harness --execution-mode live-peer`
  over checked-in suites and matrices after approval.
- Grader: JSON schema validation, deterministic fixture assertions, rubric
  grades for seeded findings, false-positive thresholds, and budget limits.
- Evidence packet: readiness report, budget estimate report,
  `tmp/evals/harness-model/report.json`, transcripts, raw model catalog
  snapshot, and rendered summary.
- Cadence: local smoke before config changes; full matrix before model
  promotion; periodic refresh when provider catalogs drift.
- Gaps / waiver: no production model default changes until failed harness rows
  are hardened and a fuller provider-backed suite passes.

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
