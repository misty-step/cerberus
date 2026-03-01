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
| Verdict | The aggregated outcome: PASS / WARN / FAIL. Emitted by aggregate-verdict.py from all reviewer verdicts |
| Reviewer | One agentic LLM-powered code reviewer. Emits a JSON verdict block. Six per full run (trace, guard, proof, atlas, fuse, craft) |
| Finding | A specific code issue identified by a reviewer. Has: severity, category, file, line, title, description, suggestion |
| SKIP | A reviewer that failed to produce a verdict (timeout, parse failure, etc.) |
| [unverified] | Pipeline-added tag indicating a finding lacked an `evidence` field (exact code quote). Currently causes severity demotion — fixing this is #305 |
| Override | A `/cerberus override sha=<sha>` comment from an authorized actor, suppressing a FAIL verdict |
| OSS action | The GitHub Action distribution (BYOK — bring your own key). This repo |
| Cerberus Cloud | Managed GitHub App (separate repo). Handles billing, quota, org controls |
| Pi runtime | The LLM invocation layer used by reviewers. Invoked via `scripts/run-reviewer.py` → `scripts/lib/runtime_facade.py` |
| Pool | A set of models that reviewers draw from randomly each run, for model diversity |

## Active Focus

- **Milestone:** PRIMARY 1: OSS Production Readiness (due 2026-03-14)
- **Key Issues:** #305 (p0, now), #256 (now), #293 (now), #278 (now)
- **Theme:** Stop false positives and false negatives. Make verdicts trustworthy enough to use as a merge gate.

## Quality Bar

- [ ] Every reviewer produces a verdict (no unexplained SKIPs)
- [ ] FAIL verdicts contain at least one finding at minor or higher severity
- [ ] No real bug rated below `minor` when 2+ reviewers agree on it
- [ ] PR comment is visible (not buried) after each push
- [ ] Verdict check accurately reflects failure mode (timeout ≠ auth error)
- [ ] Tests pass at 70%+ coverage: `python3 -m pytest tests/ --cov=scripts`

## Patterns to Follow

### Reviewer prompt structure (in .opencode/agents/*.md)
YAML frontmatter (ignored), then body is the system prompt trusted by Pi runtime.

### Error classification in run-reviewer.py
```python
# Classify exit codes to retry/skip/fail
if exit_code == 124:  # timeout
    error_class = "timeout"
elif exit_code == 0:
    error_class = "success"
else:
    error_class = "unknown"  # bug: unknown doesn't retry enough — see #293
```

### Verdict comment idempotency pattern (post-comment.sh)
```bash
# HTML marker used to find/update existing comment
MARKER="<!-- cerberus:verdict -->"
# Find existing comment ID by marker, then edit or create
```

### Model pool config (defaults/config.yml)
```yaml
model:
  default: openrouter/moonshot-ai/kimi-k2
  tiers:
    flash: [...]
    standard: [...]
    pro: [...]
```

## Lessons Learned

| Decision | Outcome | Lesson |
|----------|---------|--------|
| `[unverified]` tag demotes severity to info | Real P1 bugs invisible in review, false PASS | Evidence should annotate, not gate severity |
| minimax-m2.5 and mimo-v2-flash in flash pool | Consistent JSON contract failures = SKIP | Remove unreliable models; replace with proven ones |
| Reusable workflow @master ref with secret forwarding | Supply-chain risk rated info by reviewers | guard.md needs explicit mutable-ref + secret = major |

---
*Last updated: 2026-02-28*
*Updated during: /groom session*
