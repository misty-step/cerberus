# Make Cerberus operable by a cold agent without tribal knowledge

Priority: P1 · Status: pending · Estimate: M

## Goal
A cold agent or new contributor can find the gate, the red lines, and the real live-review prerequisites in-repo, and cannot leak a secret at the publication boundary.

## Oracle
- [ ] A root `AGENTS.md` states the real gate (`./scripts/verify.sh`), the four substrate red lines (no static reviewer roster / no prompt-or-diff in argv / no ambient creds / `spec.md` is LOCKED), which doc is canonical (`VISION.md`), and cross-references the invariant tests.
- [ ] Live-review prerequisites are documented: OpenCode install + pinned version, `OPENROUTER_API_KEY`, model id, `gh auth`, and the trusted-PATH binary-resolution rule + supported install locations (`harness.rs:784-804`).
- [ ] A secret-scan step (e.g. gitleaks) runs in `verify.sh`/CI over the working tree and diff (today: none — only runtime receipt/transcript leak checks exist).

## Children
1. Author root `AGENTS.md` (gate, four red lines, canonical-doc pointer, invariant-test signposts).
2. Document live-path prerequisites + trusted-PATH rule (shares the prereq work with ticket 006 child 1).
3. Add a secret-scan gate (gitleaks) over tree + diff to `verify.sh`/`verify.yml`.

## Notes
**Why:** lane-readiness F1-F5 (vetted: no `AGENTS.md`/`CLAUDE.md` exists). The live OpenCode path has zero documented prerequisites — a cold agent passes the entire green gate (fake binaries) while believing the live path works (F2). No secret-scan over files/history before publication (F3); runtime leak discipline is excellent but the publication axis is open. The invariants a cold agent would break (static roster, argv safety) ARE test-guarded but invisible (F4). Directly serves VISION's "long-lived substrate … operable without tribal knowledge." Credit: `verify.sh` (533 lines, every real route) + CI on push+PR with least-privilege `contents: read` are genuinely excellent.
