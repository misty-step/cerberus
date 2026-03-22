# Cerberus — Project Context

## Vision

**One-liner:** Multi-agent AI code review with provider and model diversity.

**North star:** The most rigorous automated code review system available — multiple specialized reviewers, each bringing a different perspective, producing verdicts that teams trust enough to gate merges.

**Target user:** Engineering teams shipping production software who want CI-integrated code review that catches what humans miss.

**Current focus:** Complete Elixir migration — portability (Engine extraction, CLI, Dockerfile), cleanup (decommission Python, restructure repo), then review quality (evals, prompts, observability).

**Differentiators:**
- Multi-reviewer with provider/model diversity (not single-model like competitors)
- Six specialized perspectives (correctness, security, testing, architecture, resilience, maintainability)
- Smart routing — dispatch minimum effective panel per PR
- Evidence-mandatory findings (no hallucinated suggestions)
- Configurable persona registry with per-repo overlays

## Domain Glossary

| Term | Meaning |
|------|---------|
| Perspective | A specialized review lens (correctness, security, etc.) |
| Persona | A named reviewer identity: perspective + prompt + model policy |
| Bench | The set of available reviewer personas for a repo |
| Panel | The subset of bench reviewers dispatched for a specific PR |
| Verdict | A reviewer's structured output: PASS/WARN/FAIL with findings |
| Finding | A specific code issue with severity, evidence, and location |
| Router | The component that classifies a PR and selects the panel |
| Reserve | Backup reviewers triggered on disagreement or low confidence |

## Active Focus

**Milestone:** Elixir Migration (completion phase)
**Key themes:**
1. Extract `Cerberus.Engine` — infrastructure-agnostic review core (#442)
2. Portability — Dockerfile, mix release, CLI entrypoint (#443, #444)
3. Cleanup — decommission Python (40K LOC), restructure repo (#446, #447, #448)
4. BYOK GitHub access — thread github_token per-request (#445)
5. Then: review quality, evals, prompt engineering, observability

## Quality Bar

- Every finding must include exact code evidence (1-6 lines verbatim)
- Confidence gating: < 0.7 excluded from verdict, < 0.6 not reported
- Conservative finding dedup (same-file, same-category, nearby-line)
- Override authorization chain (actor + SHA + reason)
- Eval recall target: >= 85% on gold-standard benchmark set

## Patterns to Follow

- Livebook dual-mode pattern (CLI + server from same codebase, conditional supervision tree)
- GenServer per reviewer, DynamicSupervisor for pool, SQLite store
- ReqLLM for OpenRouter calls, direct API (no Pi CLI)
- OpenTelemetry GenAI semantic conventions for LLM span attributes
- Persona prompts as plain files with hot-reload via OTP
- Alpine multi-stage Dockerfile for portable releases

## Lessons Learned

| Decision | Outcome | Lesson |
|----------|---------|--------|
| Python orchestration | 10.8K LOC, fragile shell glue | BEAM process model is the natural fit for multi-agent |
| Wave escalation | Too slow, too costly | Single-pass routed panel with reserve escalation is better |
| Pi CLI as middleman | Extra dependency, hard to debug | Direct API calls via ReqLLM are simpler |
| GHA matrix for execution | Expensive, slow startup | Fly.io (Sprites or Machines) for burst compute |
| BB Python->Elixir | 6,506->1,649 LOC, first-try success | Elixir/OTP is the right stack for agent orchestration |

**Last updated:** 2026-03-22
