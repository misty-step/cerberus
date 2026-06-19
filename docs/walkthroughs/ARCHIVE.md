# Historical Walkthrough Archive Index

Snapshot date: 2026-06-19.

This directory and the legacy `artifacts/` and `walkthrough/` roots contain
historical evidence, PR receipts, raw transcripts, and media from prior
Cerberus implementations. They are not current runtime surfaces unless a
current backlog item or retirement inventory row names a specific file as
acceptance evidence.

## Archive Policy

- Keep these files readable until a separate archive move commit records the
  destination and rollback path in
  `docs/shaping/legacy-surface-retirement.json`.
- Do not use old Python/Shell matrix walkthroughs as current architecture
  evidence. Prefer `docs/ARCHITECTURE.md`, `docs/api-contract.md`, and current
  backlog receipts.
- If a migration audit needs old behavior, cite the exact file and path rather
  than treating the whole archive root as active documentation.
- New feature work should write fresh evidence under the current backlog or
  shaping plan instead of appending to old issue walkthroughs.

## Current Historical Inventory

The `docs/walkthroughs/` count excludes this `ARCHIVE.md` index file.

| Root | Count | Contents |
|---|---:|---|
| `docs/walkthroughs/` | 34 | Issue walkthroughs, targeted test transcripts, and full validation transcripts. |
| `artifacts/` | 16 | Older PR body drafts, PR walkthroughs, and cleanup receipts. |
| `walkthrough/` | 8 | Older reviewer evidence, runtime proof text, and one prompt demo video. |

## `docs/walkthroughs/`

Issue walkthroughs and transcript files:

- `docs/walkthroughs/cli-hidden-api-key-prompt.md`
- `docs/walkthroughs/issue-290-verdict-comment-resilience.md`
- `docs/walkthroughs/issue-295-infra-review-recall.md`
- `docs/walkthroughs/issue-297-sentinel-error-tracing.md`
- `docs/walkthroughs/issue-299-deduped-verdict-findings.md`
- `docs/walkthroughs/issue-302-mutable-action-ref-severity.md`
- `docs/walkthroughs/issue-305-finding-evidence-contract.md`
- `docs/walkthroughs/issue-312-ac-compliance.md`
- `docs/walkthroughs/issue-323-review-execution-boundary.md`
- `docs/walkthroughs/issue-324-review-run-contract.md`
- `docs/walkthroughs/issue-325-github-platform-adapter-boundary.md`
- `docs/walkthroughs/issue-325-github-platform-make-validate.txt`
- `docs/walkthroughs/issue-325-github-platform-targeted-tests.txt`
- `docs/walkthroughs/issue-326-github-bootstrap-boundary.md`
- `docs/walkthroughs/issue-326-github-bootstrap-make-validate.txt`
- `docs/walkthroughs/issue-326-github-bootstrap-targeted-tests.txt`
- `docs/walkthroughs/issue-328-execution-boundary-guard.md`
- `docs/walkthroughs/issue-329-non-gha-review-runner.md`
- `docs/walkthroughs/issue-331-benchmark-planning-surface.md`
- `docs/walkthroughs/issue-334-timeout-slice-make-validate.txt`
- `docs/walkthroughs/issue-334-timeout-slice-targeted-tests.txt`
- `docs/walkthroughs/issue-334-timeout-slice.md`
- `docs/walkthroughs/issue-344-emergency-cost-control.md`
- `docs/walkthroughs/issue-355-full-validation.txt`
- `docs/walkthroughs/issue-355-parse-review-verification.txt`
- `docs/walkthroughs/issue-355-parser-diagnostics-envelope.md`
- `docs/walkthroughs/issue-380-agentic-review-evals.md`
- `docs/walkthroughs/issue-416-single-codebase-cleanup.md`
- `docs/walkthroughs/issue-418-reviewer-verdict-persistence.md`
- `docs/walkthroughs/issue-437-persisted-findings-hardening.md`
- `docs/walkthroughs/issue-443-cli-local-review.md`
- `docs/walkthroughs/issue-443-cli-review-full-validation.txt`
- `docs/walkthroughs/issue-443-cli-review-targeted.txt`
- `docs/walkthroughs/issue-446-api-dispatch-cleanup.md`

## `artifacts/`

Older PR and cleanup receipts:

- `artifacts/codex-simplify-github-review-helpers-walkthrough.md`
- `artifacts/issue-416-archive-cleanup-walkthrough.md`
- `artifacts/issue-448-elixir-cleanup-walkthrough.md`
- `artifacts/pr-282-body.md`
- `artifacts/pr-282-walkthrough.md`
- `artifacts/pr-298-walkthrough.md`
- `artifacts/pr-317-body.md`
- `artifacts/pr-317-walkthrough.md`
- `artifacts/pr-331-walkthrough.md`
- `artifacts/pr-333-walkthrough.md`
- `artifacts/pr-334-body.md`
- `artifacts/pr-365-walkthrough.md`
- `artifacts/pr-383-reviewer-delta-triage.md`
- `artifacts/pr-416-body.md`
- `artifacts/pr-448-body.md`
- `artifacts/pr-57-walkthrough.md`

## `walkthrough/`

Older raw evidence and media:

- `walkthrough/issue-293/runtime-retry-proof.txt`
- `walkthrough/issue-300-reviewer-evidence.md`
- `walkthrough/issue-317-reviewer-evidence.md`
- `walkthrough/issue-333-reviewer-evidence.md`
- `walkthrough/issue-57-reviewer-evidence.md`
- `walkthrough/pr-373/cli-hidden-api-key-prompt.mp4`
- `walkthrough/pr-373/reviewer-evidence.md`
- `walkthrough/reviewer-evidence.md`

## Current Replacement Pointers

- Current architecture: `docs/ARCHITECTURE.md`
- Current API compatibility contract: `docs/api-contract.md`
- Legacy surface retirement source of truth:
  `docs/shaping/legacy-surface-retirement.md`
- Rust review engine shaping:
  `docs/shaping/rust-review-engine-resurrection.md`
- Historical ThinkTank import inventory:
  `docs/shaping/thinktank-migration-inventory.md`
