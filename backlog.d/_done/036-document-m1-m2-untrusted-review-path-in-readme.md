# Document the M1/M2 untrusted-review path and review doctrine in README

Priority: P1 · Status: ready · Estimate: M

## Goal
README currently has zero mentions of the M1 scoped-ephemeral-key path, the M2
`container-opencode` isolation substrate, or the review-doctrine/named-dimensions
prompt content — all three are shipped, live-verified, production-enabled
capabilities (013 M1/M2 merged 2026-07-01; 023 merged 2026-07-01) with real CLI
surface, but a cold operator or agent reading README has no way to discover or
use them.

## Oracle
- [ ] README documents all 9 M1/M2 flags (`--openrouter-scoped-key`,
      `--openrouter-provisioning-key-file`, `--openrouter-provisioning-key-env`,
      `--openrouter-key-limit-usd`, `--openrouter-orphan-sweep-seconds`,
      `--harness container-opencode`, `--container-binary`, `--container-image`,
      `--container-egress-allow-host`, `--container-host-root`) — verified by
      `grep -c -- '--<flag>' README.md` returning ≥1 for each.
- [ ] README states the security model in plain language: what
      "untrusted-PR-safe" means (scoped/capped/revoked key + non-model-egress
      blocked by container) and explicitly that the local/default path is NOT
      untrusted-safe (per VISION.md Non-Goals).
- [ ] README names the review-doctrine/named-dimensions content
      (`src/review_doctrine.md`, the mandatory model-boundary dimension from
      023) at least at pointer level — what it is and where to read the full
      text.
- [ ] `./scripts/verify.sh` green (docs-only change, no code path affected).

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
