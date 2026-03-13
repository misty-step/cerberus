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
- **scope changes**: Pivoted the lane away from a bad `unverified finding` category and toward the actual contract: findings remain first-class, evidence/citations support them, prompts must quote exact code or omit the finding, and deprecated marker paths were deleted instead of preserved as compatibility shims.
- **blockers**: The open issue and PR still described weighted unverified verdict math even though the better fix was vocabulary and contract cleanup across prompts, parser, renderer, docs, and tests.
- **pattern**: When review-quality work starts inventing second-class finding types, stop and define the nouns first. Stable terminology prevents downstream parser/render drift.

## 2026-03-10 — Issue #297: sentinel error tracing for trace reviewer

- **issue**: #297
- **predicted effort**: p1 (medium — 1-2 days)
- **actual effort**: ~1.5 hours
- **scope changes**: Added prompt-contract tests plus a small lint cleanup in an adjacent prompt test file so touched-area validation stayed clean.
- **blockers**: `make validate` still fails in `ruff` on unrelated pre-existing findings across untouched repo files after the full pytest phase passed.
- **pattern**: Prompt-only fixes need an explicit RED test first; otherwise it is too easy to ship soft wording changes that do not actually lock the intended reasoning contract.

## 2026-03-11 — Issue #299: dedupe equivalent top-level verdict findings

- **issue**: #299
- **predicted effort**: p1 (medium — 1-2 days)
- **actual effort**: ~2 hours
- **scope changes**: Tightened the issue itself with a real product spec and design, then limited the implementation to the aggregate verdict renderer instead of changing reviewer verdict artifacts or parser semantics.
- **blockers**: The first merge heuristic over-collapsed exact-title findings on adjacent lines and under-collapsed wording variants because token normalization was too naive; focused regression tests exposed both failure modes quickly.
- **pattern**: For “semantic enough” render-layer dedupe, keep the heuristic conservative and pin both the merge and non-merge cases in tests. The safe shape is same-file, same-category, nearby-line agreement with explicit overlap evidence, not broad fuzzy clustering.

## 2026-03-11 — Issue #300: unused dependency findings promoted from info to minor

- **issue**: #300
- **predicted effort**: p1 (medium — 1-2 days)
- **actual effort**: ~2 hours
- **scope changes**: Added a committed reviewer-evidence walkthrough because the lane touched only backend review semantics and needed a durable, reviewer-friendly proof artifact instead of video.
- **blockers**: Running full pytest and coverage commands in parallel caused a false failure because both suites write `/tmp/verdict.json`; rerunning the gates sequentially confirmed the branch was healthy.
- **pattern**: Aggregation-only severity fixes should recompute reviewer stats in the same pass. Otherwise reporting and rendering drift even when the promoted finding itself is correct.

## 2026-03-12 — Issue #323: review execution boundary

- **issue**: #323
- **predicted effort**: p1 (large foundational lane)
- **actual effort**: ~4 hours
- **scope changes**: Shipped the smallest viable boundary cut: a provider-agnostic review-run contract, GitHub bootstrap script, shared `github_platform` transport, ADR, focused guard tests, and issue shaping/design work on the parent epic itself.
- **blockers**: `make validate` initially failed only in `ruff` because a compatibility import kept for the retry tests looked unused after the transport refactor; the fix was to make the back-compat surface explicit instead of deleting it and breaking callers/tests.
- **pattern**: Boundary refactors in mature codepaths go faster when the new deep module is introduced underneath stable compatibility seams. For Cerberus, preserving `lib.github` and `collect-overrides.py` wrapper surfaces while moving transport underneath `github_platform` kept the diff small and the tests credible.

## 2026-03-12 — Issue #328: coupling guard for execution boundary

- **issue**: #328
- **predicted effort**: p1 (small — under a day)
- **actual effort**: ~1.5 hours
- **scope changes**: Enriched the issue before coding, added one narrow execution-boundary regression test, expanded ADR 004 with explicit extension-point guidance, and added a walkthrough artifact for the lane.
- **blockers**: The first guard test overreached by flagging harmless `"gh ..."` strings in error text rather than actual subprocess call sites; narrowing the assertion to call sites kept the guard useful instead of noisy.
- **pattern**: Boundary guardrails need both halves: executable enforcement plus contributor-facing routing language. A test without the ADR becomes a trap; an ADR without the test becomes drift-prone.

## 2026-03-12 — Issue #302: mutable action ref severity in guard

- **issue**: #302
- **predicted effort**: p1 (medium — 1-2 days)
- **actual effort**: ~1.5 hours
- **scope changes**: Filled in missing issue `Product Spec` / `Intent Contract` / `Technical Design`, added a committed walkthrough artifact, and treated AC verification as prompt-contract evidence with explicit `PARTIAL` status instead of pretending to have live LLM replay proof.
- **blockers**: None in the repo gate; the only evidence gap is expected for prompt-only behavior because this lane did not add a live eval replay harness.
- **pattern**: Prompt-only review-quality fixes ship best when the issue contract, prompt text, regression test, and reviewer evidence doc all land together. Otherwise the branch passes locally but still leaves reviewers guessing about what behavior is actually protected.

## 2026-03-12 — Issue #324: complete the review-run contract boundary

- **issue**: #324
- **predicted effort**: p1 (medium — 1-2 days)
- **actual effort**: ~2 hours
- **scope changes**: Finished the already-started boundary instead of inventing a new one: enriched the existing review-run contract with branch refs and runtime-env derivation, removed review-step repo/PR env wiring from `action.yml`, added a dedicated contract doc, and shipped committed walkthrough evidence.
- **blockers**: No product blockers; the only shell hiccup was a harmless zsh `status` readonly-name collision after `gh pr create` had already opened the PR.
- **pattern**: Boundary work sticks when the contract becomes authoritative for one real lane. Leaving both the contract and raw env plumbing active in the main path keeps the new abstraction shallow and untrusted.

## 2026-03-12 — Issue #325: deepen github_platform into the review-path adapter

- **issue**: #325
- **predicted effort**: p1 (medium — 1-2 days)
- **actual effort**: ~2 hours
- **scope changes**: Tightened the issue itself before coding, then limited implementation to the review-path seam: `github_platform`, `github.py`, `github_reviews.py`, `collect-overrides.py`, focused tests, and boundary docs. Left `triage.py` and non-review admin scripts out of scope.
- **blockers**: The first test pass surfaced that `collect-overrides.py` still relied on old local wrapper behavior; moving the test expectations to the adapter boundary fixed the mismatch without widening the code change.
- **pattern**: Boundary refactors hold up better when the deep module owns intention-level operations, not just transport primitives. Leaving stable wrapper APIs in place while moving behavior downward keeps the diff reversible and the tests honest.

## 2026-03-12 — Issue #355: parser diagnostics moved behind `_diagnostics`

- **issue**: #355
- **predicted effort**: p1 (medium — 1-2 days)
- **actual effort**: ~2 hours
- **scope changes**: Kept the fix focused on parser/schema boundaries by moving stats and stale-knowledge metadata into one explicit pipeline envelope, updating parser tests, and adding branch-scoped transcript evidence instead of broad verdict-pipeline refactors.
- **blockers**: Terminal capture via `script(1)` changed the environment enough to break `tests/test_pipeline_integration.py` on `/tmp` paths even though `make validate` was green in the normal shell; switched walkthrough capture to plain `tee`.
- **pattern**: When backend-only lanes need durable walkthrough proof, prefer plain command transcripts over terminal wrappers. Some repo tests are sensitive to shell/TTY wrappers, and the evidence path should match the real validation environment.
