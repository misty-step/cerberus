# Document the M1/M2 untrusted-review path and review doctrine in README

Priority: P1 · Status: done (2026-07-03) · Estimate: M

## Goal
README currently has zero mentions of the M1 scoped-ephemeral-key path, the M2
`container-opencode` isolation substrate, or the review-doctrine/named-dimensions
prompt content — all three are shipped, live-verified, production-enabled
capabilities (013 M1/M2 merged 2026-07-01; 023 merged 2026-07-01) with real CLI
surface, but a cold operator or agent reading README has no way to discover or
use them.

## Oracle
- [x] README documents all 9 M1/M2 flags — new "Untrusted-PR review (scoped
      keys + container isolation)" section; verified live with
      `grep -c -- '--<flag>' README.md` returning ≥1 for all 10 flag strings
      checked (9 named flags plus the `--harness container-opencode` pair).
- [x] README states the security model in plain language, opening with an
      explicit "The default review path is not safe against an untrusted
      diff" statement, then explains M1 (scoped/capped/revocable key) and M2
      (container isolation + model-only egress) each in a short paragraph
      before the flag list.
- [x] README names the review-doctrine/named-dimensions content — new
      "Review doctrine" section pointing at `src/review_doctrine.md`, naming
      the mandatory model-boundary dimension (023) and the
      `review_doctrine_digest` receipt field that records which doctrine
      version governed a run.
- [x] `./scripts/verify.sh` green.

## Notes
Verified live 2026-07-01: `grep -c -- "--openrouter-scoped-key" README.md` and
the other 8 flag names all return 0. `src/main.rs` help text for these flags is
already decent (backlog 009 covered CLI `--help`), so this is purely the
README/onboarding surface, not a code gap. Do not restate the full backlog-013
verification transcript in README — link or summarize; the ticket itself
remains the source of truth for the verification evidence.

**Why:** live grep against README.md tonight (2026-07-01) found 0 hits for
every M1/M2 flag name despite both milestones being merged, live-verified, and
marked production-enabled the same day (013 status block); OVERNIGHT.md's own
per-repo focus line for cerberus names "docs hardening around the M1/M2
credential+container path" explicitly.
