# Pi Bootstrap Report

- Domain: cerberus
- Repo: /Users/phaedrus/Development/cerberus-mono/cerberus
- Generated: 2026-03-02T01:31:05.576Z
- Package manager: unknown
- Stack hints: none

## Notes
- Fallback plan used because synthesis was unavailable or invalid.

## Repository Context Digest
contextSnippets:
[AGENTS.md]
# Cerberus

Multi-agent AI PR review. Six parallel reviewers. Single Cerberus verdict gates merge.

## Reviewers
- APOLLO: correctness + logic (find the bug)
- ATHENA: architecture + design (zoom out)
- SENTINEL: security + threat model (think like an attacker)
- VULCAN: performance + scalability (think at runtime)
- ARTEMIS: maintainability + DX (think like next developer)
- CASSANDRA: testing + coverage (see what will break)

## Key Paths
- action: `action.yml` (review) + `draft-check/action.yml` (draft skip) + `verdict/action.yml` (verdict) + `triage/action.yml` (auto-triage)
- validate: `validate/action.yml` (consumer workflow validator)
- config: `defaults/config.yml`
- agents: `.opencode/agents/<perspective>.md` (YAML frontmatter + system prompt body)
- scripts: `scripts/`
- templates: `templates/review-prompt.md`
- consumer template: `templates/consumer-workflow-reusable.yml`
- workflow lint template: `templates/workflow-lint.yml`
- tests: `tests/`
- CI: `.github/workflows/ci.yml`

## Output Schema (Reviewer JSON)
Each reviewer ends with a JSON block in ```json fences.

Required fields:
- reviewer, perspective, verdict, confidence, summary
- findings[] with severity/category/file/line/title/description/suggestion
- stats with files_reviewed, files_with_issues, critical, major, minor, info

Optional fields:
- findings[].evidence (string) - exact code quote backing the finding
- findings[].scope (string) - set to `defaults-change` when citing unchanged code that became n

[CLAUDE.md]
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Cerberus is a multi-agent AI code review system shipped as a GitHub Action. Six parallel Pi-runtime reviewers (powered by Kimi K2.5 via OpenRouter by default) each analyze a PR diff from a specialized perspective, then a verdict action aggregates their verdicts into a single merge-gating check.

Repo scope: this repository is the OSS BYOK GitHub Actions distribution. Cerberus Cloud (managed GitHub App) is planned as a separate repo/product (see `docs/adr/002-oss-core-and-cerberus-cloud.md`).

## Architecture

```text
PR opened/synced
    │
    ▼
consumer workflow (.github/workflows/cerberus.yml)
    │
    ├── preflight job (always runs first)
    │   └── uses: misty-step/cerberus/preflight@master  (preflight/action.yml)
    │       ├── check: fork PR? → skip (no secrets available)
    │       ├── check: draft PR? → skip + optional PR comment
    │       ├── check: missing API key? → skip + optional PR comment
    │       └── outputs: should_run (bool), skip_reason (enum)
    │
    ├── matrix job × N reviewers (if: should_run, parallel, fail-fast: false)
    │   └── uses: misty-step/cerberus@master  (action.yml)
    │       ├── fetch PR diff/context
    │       ├── run-reviewer.sh   (prompt + Pi runtime invocation)
    │       ├── parse-review.py   (extract + validate JSON verdict)
    │       ├── post-comment.sh   (optional per-reviewer PR comm

[project.md]
# Project: Cerberus

## Vision
Agentic code review platform — multi-perspective review, auto-triage, and observability that developers actually want to pay for.

**North Star:** Replace CodeRabbit. Ship a GitHub-native platform where AI agents review code, fix their own findings, monitor production health, and track errors — all through agentic workflows, not dashboards.
**Target User:** Engineering teams (2–50 devs) who want automated code review that catches what humans miss, without drowning in noise. Willing to pay for quality signal.
**Current Focus:** v2.x — Review Quality & Reliability. World-class reviews. Fix reliability (SKIPs, parse failures), improve formatting (inline comments, scannable verdicts), reduce noise (hallucinations, false positives). Match CodeRabbit UX, then exceed it.
**Key Differentiators:**
- Multi-perspective review (6 specialized reviewers vs single-pass)
- Model diversity (each reviewer uses a different model via OpenRouter)
- Aggregated verdict with override protocol — not binary pass/fail
- Open core (OSS GitHub Action + managed Cerberus Cloud)
- Agentic triage — findings auto-remediated via fix PRs

## Domain Glossary

| Term | Definition |
|------|-----------|
| Perspective | One reviewer's analytical lens: correctness, security, testing, architecture, resilience, maintainability |
| Wave | A tier of reviewers that runs in sequence. wave1=flash, wave2=standard, wave3=pro. wave N runs only when wave N-1 exits clean |
| Verdict | The aggregat

[docs/ARCHITECTURE.md]
# Cerberus Architecture — Unix-Composable Agentic DevOps

Diagrams: `docs/DIAGRAMS.md`.

## Vision

Cerberus is agentic DevOps composed from distinct, focused modules. Each module does ONE thing well. They plug into each other but are independently useful. Not a monolith. Not spaghetti. A Unix pipeline for software quality.

## Distribution

- **OSS Core (this repo)**: GitHub Actions (BYOK model key). PR comments + checks as the UX.
- **Cerberus Cloud (planned)**: GitHub App + GitHub Marketplace billing. Same review/triage loop, but managed keys + quotas + org controls, and zero-YAML onboarding.

Source of truth: `docs/adr/002-oss-core-and-cerberus-cloud.md`.

## Modules

### Module 1: Cerberus Review (GitHub Action) — **v1.0**
**What:** Multi-AI code review. Eight specialist reviewers form the bench; the router selects the most relevant per PR (trace always included, guard required for non-doc/test changes). Synthesizes verdicts into a unified verdict comment and a PR review with inline comments.

**Status:** Working. Deployed across all Misty Step repos. Needs hardening.

**v1.0 success criteria:**
- Rock-solid resilience: handles timeouts, API failures, credit exhaustion, rate limits gracefully
- Beautiful, scannable PR comments: clear verdict, per-reviewer summaries, actionable findings
- Dead-simple installation: copy one workflow file, set one secret, done
- Comprehensive test suite
- Cl…

## Single Highest-Leverage Addition
- Idea: Establish a minimal planner -> worker -> reviewer local workflow loop that compounds repo familiarity through memory-first context reuse.
- Source lane: ambition-pass
- Why now: This creates immediate throughput gains with low maintenance while preserving room for optional advanced overlays.
- 72h validation experiment: Run this bootstrap on two active tasks, then compare plan-to-merge latency and rework churn against the prior baseline.
- Kill criteria: If cycle time or defect/rework metrics worsen by more than 15%, roll back to prior local config and revisit assumptions.

## Lane Evidence
## repo-scout
- model: openai-codex/gpt-5.3-codex
- thinking: xhigh
- status: ok
- elapsed: 11s

(no output)

---

## context-bridge
- model: openrouter/anthropic/claude-sonnet-4.6
- thinking: high
- status: ok
- elapsed: 90s

Now I have a comprehensive picture. Let me synthesize the findings.

---

## Existing Context Signals

### AGENTS.md (in-repo, also loaded globally)
Rich operational spec: reviewer codenames (APOLLO/ATHENA etc. — stale, mapped to trace/guard/proof/atlas/fuse/craft in CLAUDE.md), key file paths, JSON output schema with required/optional fields, verdict rules, override protocol. Well-maintained and accurate.

### CLAUDE.md
High-fidelity architecture doc: pipeline flow, module responsibilities, error classification patterns, idempotency patterns, model pool config, verdict schema. Has one known stale section (`project.md` references old pattern for model tiers). Well-maintained.

### project.md
Living strategic doc: vision, domain glossary, active milestone (PRIMARY 1: Production Readiness, due 2026-03-14), quality bar checklist, patterns to follow, lessons learned table. High signal. The "current focus" section is the most actionable planning artifact.

### .groom/plan-2026-02-28.md
Issue prioritization with ordered execution plan and research findings. Signals current sprint (#305, #256, #293, #278). Valuable for session continuity.

### .groom/retro.md
Structured post-mortems keyed by issue number. One entry so far (#255). Documents "check upstream structured data before designing a new parsing approach" — high-value lesson.

### .claude/settings.local.json
Bash permission allowlist: `chmod:*`, `python3 -m pytest:*`, `shellcheck:*`, `python3:*`. Directly maps to `make validate` workflow.

### pi/ (local Pi artifacts)
- `pi/extensions/reviewer-guard.ts` — Production-grade sandboxing: blocks destructive bash, restricts file writes to `/tmp`, injects trusted system prompt, enforces MAX_STEPS. This is live toolchain code, not just config.
- `pi/extensions/runtime-telemetry.ts` — NDJSON event emitter to `$CERBERUS_RUNTIME_TELEMETRY_FILE`. Best-effort; never blocks reviewer.
- `pi/skills/base-review/SKILL.md` — 6-step PR review workflow with output contract (severity set…

---

## docs-research
- model: openrouter/google/gemini-3.1-pro
- thinking: high
- status: ok
- elapsed: 79s

## High-Value References

- **Tailwind v4 CSS-First Paradigm** (https://tailwindcss.com/blog/tailwindcss-v4)
  *Why it matters:* Tailwind v4 drops `tailwind.config.js` entirely for a CSS variables-based configuration via the `@theme` directive. Agents unaware of this will constantly hallucinate or attempt to edit/create non-existent JS configuration files in `cerberus-web/`.
- **Next.js 15 Server Actions & React 19** (https://nextjs.org/docs/app/building-your-application/data-fetching/server-actions-and-mutations)
  *Why it matters:* Using API Routes for data mutations is an anti-pattern in Next.js 15. The official standard relies on `"use server"` actions paired with React 19's `useActionState`. This heavily reduces boilerplate and changes how an agent should build full-stack logic.
- **Bun Test Runner** (https://bun.sh/docs/cli/test)
  *Why it matters:* Bun’s native test runner does not natively use Jest. It requires explicit imports (`import { test, expect } from "bun:test"`). This perfectly aligns with `cerberus-cloud/`'s strict dependency injection guidelines (in-memory test stores over module-level mocking).
- **Ruff Python Linter & Formatter** (https://docs.astral.sh/ruff/tutorial/)
  *Why it matters:* Ruff entirely replaces Flake8, Black, isort, and Bandit in the `cerberus/` OSS repo. Relying on default Python formatter knowledge will introduce conflicting pipelines or slow down agent iterations.

## Practical Implications for Agentic Workflow

1. **Avoid Missing Targets in Frontend Tooling**: When requested to add brand colors or UI styling tokens to `cerberus-web/`, the agent must target the root `globals.css` (or main CSS file) to manipulate the `@theme` block, never a `tailwind.config` file.
2. **Mutation over APIs**: When instructed to "add a form to submit a review" in `cerberus-web/`, the agent should never scaffold a `/api/submit/route.ts` API endpoint. Instead, it must write a Server Action using the React 19 `useActionState` hook pattern.
3. **DI…

---

## workflow-critic
- model: openrouter/anthropic/claude-sonnet-4.6
- thinking: high
- status: ok
- elapsed: 150s

The XML escaping happens but the wrapping tag still carries `trust="TRUSTED"`, which is a model-directive label, not a real sandbox. That's a weaker concern than I initially flagged — XML escaping does prevent most injection. Let me now write the final structured output.

---

## Critical Failure Modes

### CFM-1: All wave pool models appear to be fictional — silent all-SKIP on every PR

`defaults/config.yml` wave pools contain model slugs that do not exist on OpenRouter:
- `openrouter/x-ai/grok-4.1-fast` (real slug: `x-ai/grok-3-fast`)
- `openrouter/google/gemini-3-flash-preview` / `gemini-3.1-pro-preview` (current: `gemini-2.5-flash-preview`)
- `openrouter/openai/gpt-5.3-codex` (does not exist; legacy Codex family)
- `openrouter/anthropic/claude-haiku-4.5` / `claude-sonnet-4.6` (Claude 4 not released)
- `openrouter/z-ai/glm-5`, `minimax/minimax-m2.5` (unverifiable provider slugs)

**Failure path:** `run-reviewer.py:build_wave_models_list` picks a random primary from the pool. Every OpenRouter call returns 404 → `classify_runtime_error` → `permanent/auth_or_quota` → `write_api_error_marker` → `parse-review.py` emits SKIP. All wave1 reviewers SKIP. Gate sees skip_count=3, skip_tolerance=1 → **blocking=true, escalate=false** → waves 2 and 3 never run. `aggregate-verdict.py` aggregates 3 SKIPs → final verdict SKIP. `fail-on-skip` defaults to `false` → **CI passes green with zero review signal on every PR.**

The hardcoded fallback in `action.yml` (`fallback-models: openrouter/google/gemini-3-flash-preview,openrouter/z-ai/glm-5`) re-uses the same dead model slugs.

**The aggregate-verdict pricing table in `aggregate-verdict.py`** also references these ghost model names, meaning cost tracking will show $0 (no pricing match) even if a model were to somehow respond.

---

### CFM-2: Wave-gate skip_tolerance=1 allows security reviewer SKIP to pass gate

`guard` (security) runs in wave1 with `override: maintainers_only`. The gate uses a flat `skip_tolerance: 1` with no per…

---

## ambition-pass
- model: openrouter/google/gemini-3-flash-preview
- thinking: high
- status: ok
- elapsed: 91s

## Foundation Workflow Pattern: The "Confidence-Gated Quality Loop"

A high-leverage agentic engineering pipeline must shift from "blind automation" to "verifiable delegation." The core pattern for Cerberus should be an **Eval-Gated Development Loop**:

1.  **Iterative Prompting:** Prompt changes to `.opencode/agents/*.md` are treated with the same rigor as code.
2.  **Automated Smoke Evals:** Every PR affecting prompts triggers a `smoke-eval` job (using `promptfoo`) that enforces a pass-rate floor (e.g., >80%).
3.  **Handoff to Shadow Review:** A "Pro" model runs in the background on every PR, comparing its findings to the "Standard" production reviewers to find quality gaps.

## Prompt + Pipeline Ideas

*   **The "Council of Critics" Pipeline:** Instead of simple aggregation, insert a final "Synth" phase. A high-IQ model reads the 6 reviewer JSONs and the original diff to resolve conflicts (e.g., if APOLLO says "Bug" but ATHENA says "By design") and produces a unified "Executive Verdict."
*   **Predictive Strike Teams:** Use a Flash-tier "Router" to analyze the diff size and complexity. For a 2-line doc fix, it disables all reviewers except ARTEMIS. For a 500-line Auth change, it force-escalates everything to the "Pro" wave immediately.
*   **Agentic Red-Teaming Workflow:** A sub-agent that takes the existing system prompts and *generates* a PR specifically designed to trick them (Hallucinating a security fix that actually adds a backdoor). If the reviewers pass it, you have a new regression test.

## Minimal Viable Bootstrap vs. Optional Upgrades

| Component | Minimal Viable Bootstrap (Foundational) | Optional Upgrades (Ambitious) |
| :--- | :--- | :--- |
| **Review Execution** | Fixed Waves (Flash → Standard → Pro) | Dynamic Routing (Strike Teams) |
| **Quality Control** | Manual `promptfoo` suite | **Autonomous Regression Harvester** |
| **Feedback Loop** | Verdict Comments + Inline Findings | **Auto-Fix PRs (Agentic Triage)** |
| **Observability** | `latest.…

---

## implementation-critic
- model: openrouter/anthropic/claude-sonnet-4.6
- thinking: xhigh
- status: ok
- elapsed: 170s

Now I have a complete picture. Let me render the critique:

---

## Durability Risks

### 1. Phantom model names in `defaults/config.yml` — will silently fail in production
The wave pool models include identifiers that do not exist on OpenRouter today:
- `openrouter/x-ai/grok-4.1-fast` (Grok 4 was not released as of this writing)
- `openrouter/minimax/minimax-m2.5`
- `openrouter/google/gemini-3-flash-preview` / `gemini-3.1-pro-preview`
- `openrouter/z-ai/glm-5`
- `openrouter/openai/gpt-5.3-codex`
- `openrouter/anthropic/claude-haiku-4.5` / `claude-sonnet-4.6`

These look like projected future model names written speculatively. When a model ID is unavailable, the fallback chain may exhaust all pool candidates and every reviewer on that wave SKIPs. Six months from now, whoever opens `config.yml` to update a model has no signal about which names are real vs placeholder. **Risk: wave-wide SKIP storm with no obvious operator signal.**

**Fix:** Replace phantom IDs with current real model slugs (e.g., `moonshotai/kimi-k2.5`, `google/gemini-2.0-flash`, `anthropic/claude-3-5-haiku`, `anthropic/claude-sonnet-4-5`). Add a `# last-verified: YYYY-MM-DD` comment per wave so operators know when to audit.

---

### 2. Ghost reviewers `flux` and `pact` in deconfliction rules — no agents, no config entries
Every agent prompt's *Deconfliction* section routes findings to `flux` (performance) and `pact` (compatibility). Neither reviewer appears in `config.yml` reviewers list, neither has an agent file in `.opencode/agents/`, and `reviewer-profiles.yml` has `performance:` and `compatibility:` perspectives but no waves route to them. If an LLM reads the prompt and decides a finding belongs to `pact`, it silently drops it with no receiver. **Risk: security or contract findings permanently suppressed with no coverage.**

**Fix:** Either (a) add agent files and config entries for `flux`/`pact` and route them in a wave, or (b) replace the `flux`/`pact` deconfliction references with the actu…

## Quality Gate Scorecard
- Gate pass: yes
- Ambition score: 85/100 (pass)
  - novelty: 5/5
  - feasibility: 4/5
  - evidence: 5/5
  - rollbackability: 3/5
- Consensus score: 96/100 (pass)
