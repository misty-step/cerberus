# Make Cerberus operable by a cold agent without tribal knowledge

Priority: P1 · Status: done (2026-07-02) · Estimate: M

## Goal
A cold agent or new contributor can find the gate, the red lines, and the real live-review prerequisites in-repo, and cannot leak a secret at the publication boundary.

## Oracle
- [x] A root `AGENTS.md` states the real gate (`./scripts/verify.sh`), the four substrate red lines (no static reviewer roster / no prompt-or-diff in argv / no ambient creds / `spec.md` is LOCKED), which doc is canonical (`VISION.md`), and cross-references the invariant tests — `AGENTS.md` now has a "Red lines" section naming all four with the exact test names (`redacts_prompt_file_from_execution_plan_args`, `child_env_uses_only_allowlist`), noting the roster/spec-lock rules are governance, not test-enforced (honest, not a false test-coverage claim).
- [x] Live-review prerequisites are documented — `AGENTS.md` "Live-review prerequisites" section: opencode install (no pinned version exists anywhere in-repo today — stated honestly as a known gap, not invented), `OPENROUTER_API_KEY`/`--openrouter-scoped-key`, `--model`, explicit `gh` token (not ambient auth — matches the real `resolve_github_token` behavior), Docker for `container-opencode`, and the exact trusted-PATH search list pulled live from `harness::trusted_executable_search_path`.
- [x] A secret-scan step (gitleaks) runs in `verify.sh`/CI over the working tree — added, gated on `gitleaks` being installed locally (skip, not fail) with a real install step in `verify.yml` so CI always has it; `.gitleaks.toml` extends the default rule set and excludes only `target/` (build output, never source). No allowlist mechanism for an individual finding — a true positive must be removed.

## Children
1. Author root `AGENTS.md` (gate, four red lines, canonical-doc pointer, invariant-test signposts).
2. Document live-path prerequisites + trusted-PATH rule (shares the prereq work with ticket 006 child 1).
3. Add a secret-scan gate (gitleaks) over tree + diff to `verify.sh`/`verify.yml`.

## Notes
**Why:** lane-readiness F1-F5 (vetted: no `AGENTS.md`/`CLAUDE.md` exists). The live OpenCode path has zero documented prerequisites — a cold agent passes the entire green gate (fake binaries) while believing the live path works (F2). No secret-scan over files/history before publication (F3); runtime leak discipline is excellent but the publication axis is open. The invariants a cold agent would break (static roster, argv safety) ARE test-guarded but invisible (F4). Directly serves VISION's "long-lived substrate … operable without tribal knowledge." Credit: `verify.sh` (533 lines, every real route) + CI on push+PR with least-privilege `contents: read` are genuinely excellent.
