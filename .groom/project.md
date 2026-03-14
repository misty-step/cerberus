# Cerberus — Project Context

## Vision

**One-liner:** Multi-agent AI code review with provider and model diversity.

**North star:** The most rigorous automated code review system available — multiple specialized reviewers, each bringing a different perspective, producing verdicts that teams trust enough to gate merges.

**Target user:** Engineering teams shipping production software who want CI-integrated code review that catches what humans miss.

**Current focus:** Migrate from Python/Shell/GitHub Actions to Elixir/OTP. Converge architecture with Bitterblossom for dual-mode operation (standalone + BB module).

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

**Milestone:** Elixir Migration
**Key themes:**
1. Port engine to Elixir/OTP (ReqLLM + Instructor + sprites-ex)
2. Eliminate waves — single-pass routed execution with reserve escalation
3. Add observability (OpenTelemetry -> Langfuse) and cost monitoring
4. Phoenix LiveView dashboard
5. Bitterblossom Worker behaviour for dual-mode operation
6. Eval suite hardening (SWR-Bench, CR-Bench, promptfoo)

## Quality Bar

- Every finding must include exact code evidence (1-6 lines verbatim)
- Confidence gating: < 0.7 excluded from verdict, < 0.6 not reported
- Conservative finding dedup (same-file, same-category, nearby-line)
- Override authorization chain (actor + SHA + reason)
- Eval recall target: >= 85% on gold-standard benchmark set

## Patterns to Follow

- Bitterblossom conductor patterns (GenServer per run, DynamicSupervisor, SQLite store)
- ReqLLM for OpenRouter calls, Instructor for structured output
- OpenTelemetry GenAI semantic conventions for LLM span attributes
- Persona prompts as plain files with hot-reload via OTP

## Lessons Learned

| Decision | Outcome | Lesson |
|----------|---------|--------|
| Python orchestration | 10.8K LOC, fragile shell glue | BEAM process model is the natural fit for multi-agent |
| Wave escalation | Too slow, too costly | Single-pass routed panel with reserve escalation is better |
| Pi CLI as middleman | Extra dependency, hard to debug | Direct API calls via ReqLLM are simpler |
| GHA matrix for execution | Expensive, slow startup | Fly.io (Sprites or Machines) for burst compute |
| BB Python->Elixir | 6,506->1,649 LOC, first-try success | Elixir/OTP is the right stack for agent orchestration |

**Last updated:** 2026-03-14
