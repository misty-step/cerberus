---
shaping: true
---

# Reviewer Overhaul — Shaping

## Frame

**Source:** Issue #134 (closed), voice transcript session 2026-02-21

**Problem:** Cerberus shipped a 12-reviewer bench and LLM router, but several reviewers produce low signal (documentation, observability, dependencies), the model pool lacks diversity/cost optimization, and "Cerberus Council" branding creates noise in GitHub UI. The system works but isn't tuned.

**Outcome:** A tight bench of high-signal reviewers, a cost-efficient model pool, and clean branding that looks professional in GitHub checks UI.

---

## Requirements (R)

| ID | Requirement | Status |
|----|-------------|--------|
| R0 | Every reviewer perspective must produce signal LLMs are actually good at | Core goal |
| R1 | Check names in GitHub UI are clean and scannable (`Cerberus / Correctness`) | Must-have |
| R2 | "Council" language eliminated from all user-facing surfaces | Must-have |
| R3 | All models in pool, randomly assigned per run — diverse model exposure | Must-have |
| R4 | Router selects a relevant panel per PR (not all reviewers every time) | Must-have (exists) |
| R5 | Each reviewer has a well-developed prompt with deconfliction rules | Must-have |
| R6 | Gemini 3.1 Pro stays in pool for critical-tier experiments | Must-have |
| R7 | Bench size stays manageable for router (8-10 perspectives max) | Must-have |
| R8 | Internal file/variable names migrate from "council" to "cerberus" | Nice-to-have |

---

## Current State (CURRENT)

### Bench (12 reviewers)

| Codename | Perspective | Model | Signal Quality |
|----------|-------------|-------|----------------|
| trace | correctness | kimi-k2.5 (pinned) | High |
| atlas | architecture | glm-5 (pinned) | Medium |
| guard | security | minimax-m2.5 (pinned) | High |
| flux | performance | gemini-3-flash (pinned) | Medium-High |
| craft | maintainability | kimi-k2.5 (pinned) | Medium |
| proof | testing | gemini-3-flash (pinned) | Medium-High |
| scribe | documentation | pool | Low — nags about docstrings |
| fuse | resilience | pool | Medium |
| pact | compatibility | pool | Medium |
| chain | dependencies | pool | Low — Dependabot does this better |
| anchor | data-integrity | pool | Low — too narrow |
| signal | observability | pool | Low — LLMs bad at this |

### Model Pool (6 models)

| Model | Input $/M | Output $/M | Notes |
|-------|-----------|------------|-------|
| kimi-k2.5 | $0.60 | $2.50 | Strong coder, reliable |
| minimax-m2.5 | $0.26 | $1.50 | Good value |
| gemini-3.1-pro-preview | $2.00 | $12.00 | Way too expensive for pool |
| gemini-3-flash-preview | $0.10 | $0.40 | Fast, cheap, decent |
| deepseek-v3.2 | $0.27 | $1.10 | Good coder |
| glm-5 | $0.43 | $1.70 | Solid generalist |

### Naming (current surfaces)

| Surface | Current | Problem |
|---------|---------|---------|
| Consumer workflow name | `Cerberus` | Fine |
| Check prefix | `Cerberus /` | Fine |
| README quick start | `name: Cerberus Council` | Stale |
| Verdict action name | `Cerberus Verdict` | Fine |
| Internal files | `council-verdict.json`, `render-council-comment.py`, `post-council-review.py` | "Council" everywhere |
| PR comment header | `## Cerberus Verdict: PASS` | Fine (already uses "Cerberus") |
| HTML marker | `<!-- cerberus:council -->` | Should be `<!-- cerberus:verdict -->` |
| Triage references | `*Cerberus Council*`, `COUNCIL_MARKER` | Should be `*Cerberus*` |
| Override command | `/cerberus override` | Fine |

---

## Shapes

### A: Trim bench to 8, clean naming, optimize pool

The conservative approach — remove low-signal reviewers, fix naming, rebalance pool.

| Part | Mechanism |
|------|-----------|
| **A1** | Remove 4 low-signal reviewers: scribe, chain, anchor, signal |
| **A2** | Fold concurrency concerns into trace's prompt (correctness already handles race conditions) |
| **A3** | Fold API design concerns into pact's prompt (compatibility already handles client impact) |
| **A4** | Remove gemini-3.1-pro from pool (too expensive). Add qwen3-coder ($0.22), mimo-v2-flash ($0.09), devstral-2 ($0.15) |
| **A5** | Rename all user-facing "Council" references to "Cerberus" |
| **A6** | Rename internal files: `council-verdict.json` → `verdict.json`, script names, markers |
| **A7** | Update README with correct bench (8 reviewers, not 6 legacy names) |
| **A8** | Update router fallback_panel and panel_size to match new bench size |

### B: Trim bench to 8, model-per-perspective assignment

Same as A but with hand-assigned models per perspective instead of pool.

| Part | Mechanism |
|------|-----------|
| **B1-B3** | Same as A1-A3 (trim bench) |
| **B4** | Hand-assign best model per perspective based on known strengths |
| **B5** | Eliminate pool entirely — every reviewer gets a specific model |
| **B6-B8** | Same as A5-A8 (naming, README, router) |

### C: Trim bench to 8, hybrid assignment (hand-pin + pool)

Same trim, but pin models where strong signal, pool for the rest.

| Part | Mechanism |
|------|-----------|
| **C1-C3** | Same as A1-A3 (trim bench) |
| **C4** | Pin models with proven strength: trace→kimi-k2.5, guard→minimax-m2.5 |
| **C5** | Pool remaining reviewers across cost-optimized model set |
| **C6** | Pool composition: kimi-k2.5, minimax-m2.5, gemini-3-flash, deepseek-v3.2, glm-5, qwen3-coder, mimo-v2-flash, devstral-2 |
| **C7-C9** | Same as A5-A8 (naming, README, router) |

---

## Fit Check

| Req | Requirement | Status | A | B | C |
|-----|-------------|--------|---|---|---|
| R0 | Every perspective must produce signal LLMs are actually good at | Core goal | ✅ | ✅ | ✅ |
| R1 | Check names clean and scannable | Must-have | ✅ | ✅ | ✅ |
| R2 | "Council" eliminated from user-facing surfaces | Must-have | ✅ | ✅ | ✅ |
| R3 | All models in pool, randomly assigned per run | Must-have | ✅ | ❌ | ❌ |
| R4 | Router selects relevant panel per PR | Must-have | ✅ | ✅ | ✅ |
| R5 | Each reviewer has well-developed prompt with deconfliction | Must-have | ✅ | ✅ | ✅ |
| R6 | Gemini 3.1 Pro stays in pool | Must-have | ✅ | ❌ | ✅ |
| R7 | Bench size stays manageable (8-10) | Must-have | ✅ | ✅ | ✅ |
| R8 | Internal names migrate from "council" to "cerberus" | Nice-to-have | ✅ | ✅ | ✅ |

**Notes:**
- B fails R3: No pool — every reviewer gets a fixed model.
- B fails R6: Hand-assigned models may exclude Gemini 3.1 Pro from perspectives where it's not "optimal."
- C fails R3: Hybrid pinning means some reviewers don't get random pool assignment.

---

## Selected Shape: A (Pool Everything)

All 8 reviewers draw from the full model pool on each run. No pinning. Gemini 3.1 Pro stays in the pool — it's a powerful model worth keeping for intense reviews, and we want to experiment with offering it in a paid tier.

---

## Detail A: Proposed Bench

### Final 8 Reviewers

| Codename | Perspective | Cognitive Mode | Model | Override Policy |
|----------|-------------|----------------|-------|-----------------|
| trace | correctness | Find the bug | pool | pr_author |
| guard | security | Think like an attacker | pool | maintainers_only |
| atlas | architecture | Zoom out | pool | pr_author |
| flux | performance | Think at runtime | pool | pr_author |
| proof | testing | See what will break | pool | pr_author |
| craft | maintainability | Think like the next dev | pool | pr_author |
| fuse | resilience | What happens when it fails | pool | pr_author |
| pact | compatibility | Trace the client impact | pool | pr_author |

### Removed Reviewers (with rationale)

| Codename | Perspective | Why Cut |
|----------|-------------|---------|
| scribe | documentation | Low signal — nags about docstrings and comments. Not what LLMs are good at. |
| chain | dependencies | Dependabot/Renovate do this better with actual vulnerability databases. |
| anchor | data-integrity | Too narrow. Migration safety folds into correctness (trace). Schema concerns fold into compatibility (pact). |
| signal | observability | LLMs are bad at judging whether logging is sufficient without runtime context. |

### Folded Concerns

| Concern | Folded Into | How |
|---------|-------------|-----|
| Concurrency/race conditions | trace (correctness) | Already in correctness prompt's primary focus. Expand slightly. |
| API design | pact (compatibility) | Client impact is the compatibility perspective's core job. |
| Data migration safety | trace (correctness) | Data loss from bad migrations is a correctness bug. |
| Schema integrity | pact (compatibility) | Breaking schema changes are client compatibility issues. |

### Model Pool (A4)

All models in the pool, randomly assigned per run. Gemini 3.1 Pro stays — powerful model for critical reviews, future paid-tier candidate.

| Model | Input $/M | Output $/M | Context | Strength |
|-------|-----------|------------|---------|----------|
| kimi-k2.5 | $0.60 | $2.50 | 128K | Strong coder, reliable JSON output |
| minimax-m2.5 | $0.26 | $1.50 | 1M | Good value, huge context |
| gemini-3.1-pro | $2.00 | $12.00 | 1M | Most powerful, critical-tier candidate |
| gemini-3-flash | $0.10 | $0.40 | 1M | Fast, cheap, good for exploration |
| deepseek-v3.2 | $0.27 | $1.10 | 128K | Strong coder |
| glm-5 | $0.43 | $1.70 | 128K | Solid generalist |
| qwen3-coder | $0.22 | $1.00 | 128K | New, code-focused, cheap |
| mimo-v2-flash | $0.09 | $0.29 | 128K | Cheapest option, surprisingly capable |
| devstral-2 | $0.15 | $0.60 | 128K | Mistral's code model, good value |

**Cost per PR (5 reviewers, ~50K input / ~10K output tokens each):**
- Cheapest panel: ~$0.04 (all mimo-v2-flash)
- Average panel: ~$0.20 (mixed pool)
- Most expensive panel: ~$1.10 (all gemini-3.1-pro)

### Naming Changes (A5-A7)

**Language rules:**

| Context | Use | Never |
|---------|-----|-------|
| The system | "Cerberus" | "Cerberus Council", "the Council" |
| The verdict | "Cerberus verdict" | "council verdict" |
| A reviewer | "trace" or "the correctness reviewer" | "TRACE", "APOLLO" |
| All reviewers | "Cerberus reviewers" or "the bench" | "council members" |
| GitHub check | `Cerberus / Correctness` | `Cerberus Council / Correctness (Pull Request)` |

**File renames:**

| Current | New |
|---------|-----|
| `council-verdict.json` (artifact) | `verdict.json` |
| `render-council-comment.py` | `render-verdict-comment.py` |
| `post-council-review.py` | `post-verdict-review.py` |
| `render_council_comment.py` (lib) | `render_verdict_comment.py` |
| `<!-- cerberus:council -->` (marker) | `<!-- cerberus:verdict -->` |
| `COUNCIL_MARKER` (triage.py) | `VERDICT_MARKER` |
| `council_verdict` (quality-report key) | `verdict` |

**User-facing text updates:**

| File | Change |
|------|--------|
| README.md | Update bench table (8 reviewers, new codenames), remove "Council" references |
| templates/consumer-workflow.yml | Already clean (`name: Cerberus`), update matrix to 8 reviewers |
| defaults/config.yml | Remove 4 reviewers, update `council_verdict:` key to `verdict:` |

### Router Updates (A8)

| Setting | Current | New |
|---------|---------|-----|
| `panel_size` | 5 | 5 (keep — 5 of 8 is a good ratio) |
| `always_include` | `[trace]` | `[trace]` (keep) |
| `include_if_code_changed` | `[guard]` | `[guard]` (keep) |
| `fallback_panel` | `[trace, atlas, guard, craft, proof]` | `[trace, atlas, guard, craft, proof]` (keep — same 5) |

Router needs to know the new bench of 8 (not 12) so it doesn't try to select removed perspectives.

---

## Implementation Slices

### V1: Naming cleanup
- Rename files, markers, variables from "council" to "cerberus"/"verdict"
- Update README bench table
- Update config key names
- No behavior changes — pure rename

### V2: Bench trim
- Remove 4 reviewers from config and delete their agent files
- Update router to use 8-perspective bench
- Fold concurrency into trace prompt, API design into pact prompt
- Update consumer workflow template matrix
- Update deconfliction sections in remaining 8 prompts

### V3: Model pool expansion
- Add qwen3-coder, mimo-v2-flash, devstral-2 to pool
- All reviewers set to `model: pool` (remove any pinned assignments)
- Verify new models work with OpenCode CLI + OpenRouter

### V4: Prompt refinement
- Review and improve all 8 prompts for quality
- Ensure consistent structure across all prompts
- Add/improve few-shot examples where weak
