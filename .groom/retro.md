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

## 2026-03-10 — Issue #282: Timeout/auth skip classification in parse-review

- **issue**: #282
- **predicted effort**: p1 (small — under a day)
- **actual effort**: ~2 hours
- **scope changes**: Tightened auth-only heuristics in `parse-review.py`, added timeout-vs-auth regression coverage, and corrected rate-limit operator guidance so non-auth SKIPs no longer point users at API keys.
- **blockers**: `make validate` passed the full pytest phase (`1526 passed, 1 skipped`) but failed later in `ruff` on unrelated pre-existing lint debt outside this diff.
- **pattern**: Skip-classification bugs are cross-boundary contract bugs. Fix the classifier and pin the emitted titles/suggestions with regression tests instead of patching downstream comment renderers.

## 2026-03-10 — Issue #290: Verdict job should not fail on transient PASS comment timeouts

- **issue**: #290
- **predicted effort**: p1 (small-medium)
- **actual effort**: ~1 hour
- **scope changes**: Added a configurable transient-exit policy to the shared GitHub comment helper, extended transient detection to TCP timeouts, and added a walkthrough artifact for the verdict path.
- **blockers**: `make validate` still fails in `ruff` on unrelated pre-existing lint debt after the full pytest suite passes.
- **pattern**: Keep transport retry detection centralized, but let the caller decide whether a transient delivery failure is merge-blocking. That preserves one retry path without flattening distinct workflow semantics.

## 2026-03-10 — Issue #295: infra review recall hardening

- **issue**: #295
- **predicted effort**: p1 (medium — 1-2 days)
- **actual effort**: ~2 hours
- **scope changes**: Tightened `trace` and `guard` prompt guidance for Dockerfile / `.dockerignore` PRs, added parser contract comments, and introduced focused regression tests for the new infra-review instructions.
- **blockers**: The issue assumed `suggestion_verified` still demoted severity, but the parser/tests already preserved severity. The implementation had to pivot from behavior change to contract codification.
- **pattern**: For review-quality issues, re-read the parser tests before changing parser logic. Prompt regressions often look like parser bugs in issue reports, but the real fix may be narrower and safer at the reviewer-instruction layer.

## 2026-03-11 — Issue #298: swallowed-error propagation guidance for trace

- **issue**: #298
- **predicted effort**: p1 (medium — 1-2 days)
- **actual effort**: ~2 hours
- **scope changes**: Added a focused prompt-contract test file and a promptfoo fixture, not just the prompt wording itself, so the swallowed-error recall lane has both unit-style and eval-style coverage.
- **blockers**: `make validate` initially passed the full pytest phase (`1548 passed, 1 skipped`) but failed in `ruff` on unrelated pre-existing lint debt across untouched files; that gate debt was then fixed in this lane so the final branch shipped green.
- **pattern**: Prompt-quality fixes hold better when the issue ships with one named regression file and one eval fixture. Text-only prompt edits are too easy to lose in later prompt churn.

## 2026-03-11 — Issue #305: findings are first-class and evidence supports them

- **issue**: #305
- **predicted effort**: p1 (medium — 1-2 days)
- **actual effort**: ~2 hours
- **scope changes**: Pivoted the lane away from a bad `unverified finding` category and toward the actual contract: findings remain first-class, evidence/citations support them, prompts must quote exact code or omit the finding, and parser/renderer paths only retain legacy-marker cleanup.
- **blockers**: The open issue and PR still described weighted unverified verdict math even though the better fix was vocabulary and contract cleanup across prompts, parser, renderer, docs, and tests.
- **pattern**: When review-quality work starts inventing second-class finding types, stop and define the nouns first. Stable terminology prevents downstream parser/render drift.
