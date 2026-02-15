# Cerberus Architecture — Unix-Composable Agentic DevOps

## Vision

Cerberus is agentic DevOps composed from distinct, focused modules. Each module does ONE thing well. They plug into each other but are independently useful. Not a monolith. Not spaghetti. A Unix pipeline for software quality.

## Modules

### Module 1: Council Review (GitHub Action) — **v1.0**
**What:** Multi-AI code review council. 6 specialist reviewers analyze every PR from different angles (correctness, architecture, security, performance, maintainability, testing). Synthesizes verdicts into a unified council comment and a PR review with inline comments.

**Status:** Working. Deployed across all Misty Step repos. Needs hardening.

**v1.0 success criteria:**
- Rock-solid resilience: handles timeouts, API failures, credit exhaustion, rate limits gracefully
- Beautiful, scannable PR comments: clear verdict, per-reviewer summaries, actionable findings
- Dead-simple installation: copy one workflow file, set one secret, done
- Comprehensive test suite
- Clean documentation

### Module 2: Auto-Triage Agent — **v1.1**
**What:** When the council identifies failures or issues, an auto-triage agent can diagnose root causes and optionally push fixes.

**Key design constraint: NO INFINITE LOOPS.**
- Circuit breaker: max 1 triage attempt per PR per council run
- Triage commits are tagged `[triage]` — council skips these commits
- If triage fix doesn't resolve the issue, it opens a comment explaining what it tried and stops
- Configurable: off / diagnose-only / diagnose-and-fix

**Trigger modes:**
1. Automatic: council FAIL verdict triggers triage
2. Manual: comment command (`/cerberus triage`) triggers triage
3. Scheduled: periodic triage of open PRs with unresolved findings

**Current implementation status (baseline):**
- Separate triage composite action (`triage/action.yml`) with runtime in `scripts/triage.py`
- Supported modes: `off`, `diagnose`, `fix`
- Circuit breakers implemented:
  - commit-tag guard (`[triage]`)
  - max attempts per PR+SHA via triage comment markers
  - global kill switch (`CERBERUS_TRIAGE=off`)
- Trigger routing implemented for `pull_request`, `issue_comment`, and `schedule`

### Module 3: Health Check Monitors — **v2.0**
**What:** Agentic uptime monitoring. Goes beyond "is it responding?" to "is it working correctly?"

**Capabilities:**
- HTTP health checks with intelligent response validation
- API contract verification (schema drift detection)
- Performance regression detection
- Certificate expiry monitoring
- DNS resolution monitoring

**Integration:** Results feed into Status Pages module. Failures trigger triage module.

### Module 4: Error Tracking & Logging — **v2.0**
**What:** Agentic Sentry replacement. Ingests errors, groups them intelligently, auto-triages.

**Capabilities:**
- Error ingestion endpoint (SDK-compatible or webhook-based)
- AI-powered error grouping (semantic, not just stack trace matching)
- Automatic severity classification
- Error → Issue → PR pipeline (zero-tolerance: every error = a fix)

**Integration:** Errors trigger triage module. Results feed into Status Pages.

### Module 5: Status Pages — **v2.0**
**What:** Public-facing status pages synthesized from health checks and error tracking.

**Capabilities:**
- Auto-generated from health check and error data
- Incident detection and reporting
- Historical uptime tracking
- Embeddable status badges

**Integration:** Consumes data from Health Checks and Error Tracking modules.

## Architecture Principles

1. **Each module is a separate, independently deployable component.** Council is a GitHub Action. Health Checks could be a standalone service. They share interfaces, not code.

2. **Composition over coupling.** Modules communicate through well-defined interfaces (webhooks, GitHub events, shared config). No direct imports between modules.

3. **Fail loud, fail safe.** Every module must handle its own failure modes gracefully. No silent failures. If something breaks, it reports what happened and stops cleanly.

4. **Configuration is declarative.** One `cerberus.yml` config file controls all modules. Each module reads its own section. Adding a module = adding a section to config.

5. **Progressive enhancement.** Install just the council? Works. Add triage? Works. Add health checks? Works. Each module enhances the others but doesn't require them.

## v1.0 Game Plan (Council Review Polish)

### Phase 1: Resilience (P0)
- [x] Timeout handling: per-reviewer timeouts with graceful degradation
- [x] API failure handling: retry with backoff, skip reviewer on persistent failure
- [x] Credit/token exhaustion: detect 402/429 errors, degrade gracefully, alert
- [x] Multi-provider fallback: if primary API fails, try secondary (fallback-models chain)
- [ ] Rate limit handling: respect GitHub API secondary rate limits

### Phase 2: Report Quality (P0)
- [x] Redesign PR comment format: clear verdict header, collapsible sections, severity indicators
- [x] Per-reviewer summary with pass/fail/skip status and key findings
- [x] Actionable findings: file + line references, suggested fixes
- [x] Diff size context: show what was reviewed (files changed, lines)
- [x] Timing info: how long each reviewer took

### Phase 3: Installation & DX (P1)
- [x] One-file installation: single workflow YAML, one secret
- [ ] Auto-detection of project type (language, framework)
- [x] Sensible defaults that work for 90% of repos
- [x] Clear error messages for misconfiguration
- [x] README with quick start, configuration reference, examples

### Phase 4: Testing & Stability (P1)
- [x] Unit tests for parse-review.py, aggregate-verdict.py
- [x] Integration test: mock API responses, verify end-to-end
- [x] Edge case coverage: empty diffs, huge diffs, binary files, no reviewers available
- [ ] CI on cerberus repo itself (dogfooding)

### Phase 5: Documentation (P2)
- [x] Architecture decision records (docs/adr/)
- [x] Configuration reference (README inputs tables)
- [ ] Troubleshooting guide
- [x] Contributing guide (CONTRIBUTING.md)
