# Vision

## One-Liner
Agentic code quality platform — multi-perspective review, auto-triage, and observability that developers actually want to pay for.

## North Star
Replace CodeRabbit. Ship a GitHub-native platform where AI agents review code, fix their own findings, monitor production health, and track errors — all through agentic workflows, not dashboards.

## Competitive Position

CodeRabbit: $30/seat/mo (GitHub Marketplace). Single-model, single-pass review with inline comments and conversational follow-up.

Cerberus differentiators:
- **Multi-perspective council** — 6 specialized reviewers vs single-pass
- **Model diversity** — each reviewer can use a different model (Kimi, Gemini, DeepSeek, GLM, Minimax, Qwen)
- **Council verdict with override protocol** — not binary pass/fail
- **Open core** — OSS GitHub Action (BYOK) + optional managed Cerberus Cloud
- **Agentic triage** — findings auto-remediated via fix PRs
- **Observability modules** — health checks, error tracking, status pages (future)

## Packaging

- **OSS**: GitHub Actions (bring your own model key)
- **Cloud**: GitHub App + GitHub Marketplace billing (managed keys, quotas, org controls)

## Target User
Engineering teams (2-50 devs) who want automated code review that catches what humans miss, without drowning in noise. Willing to pay for quality signal.

## Roadmap

### v2.x: Review Quality & Reliability (current)
Make reviews world-class. Fix reliability (SKIPs, parse failures), improve formatting (inline comments, scannable council), reduce noise (hallucinations, pre-existing issues, false positives). Match CodeRabbit UX, then exceed it.

### v3.0: Agentic Triage
Generalize the triage agent to accept findings from any source. Council flags an issue → triage agent opens a fix PR → Cerberus re-reviews the fix. Loop guards prevent infinite cycles.

### v4.0: Observability Platform
Three new modules, each a deep module with a simple interface:
- **Health Checks** — agentic UptimeRobot. Periodic endpoint monitoring, alerting.
- **Error Tracking** — agentic Sentry. Log/error monitoring, automatic deploy rollbacks on error spikes.
- **Status Pages** — auto-generated public service status from health check data.

Each module triggers auto-triage on failures.

## Design Principles

- **Agentic, not dashboard** — workflows and PR comments, not web UIs
- **Unix philosophy** — each module does one thing well, composes with others
- **Deep modules** (Ousterhout) — simple interfaces, complex internals
- **Generative UI** where interfaces are needed (Vercel AI SDK patterns)
- **Model-agnostic** — any model via OpenRouter, per-reviewer diversity
- **Zero-config defaults, deep config when needed**

---
*Last updated: 2026-02-16*
*Updated during: productization discussion*
