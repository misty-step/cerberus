# Implementation Retrospective

<!-- Append entries with /retro append. Do not hand-edit. -->

## 2026-02-23 — Issue #255: SKIP root-cause diagnostics in verdict comments

- **issue**: #255
- **predicted effort**: p1 (medium — 1-2 days)
- **actual effort**: ~3 hours (single session: autopilot → pr-fix → pr-polish)
- **scope changes**: Added cross-boundary contract tests (not in original issue) and extended `detect_skip_banner` to cover parse-failure/rate_limit/service_unavailable (adjacent fix surfaced during implementation).
- **blockers**: One test failure from word-boundary regex (`\bRATE_LIMIT\b` vs `RATE_LIMITED`). One always-true assertion caught in hindsight review pass.
- **pattern**: Structured finding fields (`category`, `title`) from `parse-review.py` already carried all the needed signal — the fix was purely in the render layer. No changes needed to the parse layer. When implementing diagnostic features, check whether upstream already produces structured data before designing a new parsing approach.

## 2026-03-03 — Issue #310: Spec-aware reviews inject AC context

- **issue**: #310
- **predicted effort**: p1 (medium — 1-2 days)
- **actual effort**: ~2.5 hours
- **scope changes**: Added linked-issue AC bootstrap in `action.yml` plus AC parsing/dedup logic in prompt renderer; added focused prompt tests.
- **blockers**: Initial YAML heredoc indentation broke action parsing; replaced with one-line python commands in run block.
- **pattern**: Keep CI action shell blocks heredoc-free when possible; small parsing helpers in Python are safer than multiline embedded scripts for YAML stability.

## 2026-03-08 — Issue #273: CLI test coverage and package-name hardening for cerberus init

- **issue**: #273
- **predicted effort**: p1 (medium — 1-2 days)
- **actual effort**: ~1.5 hours
- **scope changes**: Added one extra guard test to lock the README `npx` command to `package.json` so the publish surface cannot silently drift after the package rename.
- **blockers**: `make validate` failed in `ruff` on pre-existing unrelated test-file violations after the full pytest stage passed.
- **pattern**: For small CLIs, failure-path coverage is usually enough to prove the implementation already holds; the higher-leverage fix was metadata/documentation hardening plus a drift test, not a CLI rewrite.

## 2026-03-09 — Issue #336: adjacent-regression checks for workflow and infra PRs

- **issue**: #336
- **predicted effort**: p1 (medium — 1-2 days)
- **actual effort**: ~1.5 hours
- **scope changes**: Added a shared workflow/infra adjacency checklist, reinforced it in atlas/craft, and locked a `volume#407`-style replay fixture into eval coverage.
- **blockers**: Full repo tests passed, but `ruff` and `shellcheck` still fail on unrelated pre-existing findings in untouched files.
- **pattern**: Prompt regressions need both instruction-level coverage and a named replay fixture; prompt text alone is too easy to drift without a concrete benchmark case.
