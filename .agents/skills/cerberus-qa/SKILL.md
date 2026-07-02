---
name: cerberus-qa
description: |
  QA Cerberus changes by exercising the real review pipeline, not just tests.
  Cerberus is a code-review runner (Rust contracts + a master reviewer over an
  OpenCode/OMP substrate), so "verify.sh green" proves the machinery, NOT that
  the reviewer is good. "Tests pass" is not QA. Use when: "QA this", "verify
  the reviewer", "smoke test cerberus", "did the doctrine/prompt change help",
  "test the review". Trigger: /cerberus-qa.
argument-hint: "[fixture|live-review|review-pr|render|prompt-change]"
---

# cerberus-qa

QA in Cerberus means verifying the surface that changed against a real review.
`./scripts/verify.sh` is the deterministic gate (fmt, clippy, tests, fixture
reviews, OpenCode/OMP smoke via fake binaries, `review-pr` via a fake `gh`) — it
is **necessary but not sufficient**. It cannot tell you whether the reviewing
*brain* got better: fixtures replay canned model output. A prompt, doctrine,
context, or model change is only QA'd by a **live review of a real diff + a human
read of groundedness** (the `evidence/self-review-001/` pattern).

## Surfaces

| Changed area | Surface | QA path |
|---|---|---|
| `src/schema.rs`, `src/validation.rs`, `src/digest.rs`, `src/render.rs`, `src/receipt.rs` | Rust contracts | `./scripts/verify.sh` — deterministic; inspect the rendered markdown/artifact, not just exit 0 |
| `src/prompt.rs`, `src/review_doctrine.md` | Reviewing brain | **Live review** (below) + human read: are findings real and grounded, or plausible noise? verify.sh CANNOT prove this |
| `src/harness.rs`, substrate configs | Substrate wiring | Live `review` against a real checkout with `--harness opencode`; confirm the agent actually explored (transcript shows git/grep), not just read the diff |
| `src/post.rs` | GitHub post path | `review-pr --post` twice on a frozen-head PR; confirm update-not-duplicate (idempotency) |
| `src/request.rs`, `src/main.rs` | CLI surface | `request` / `review` / `render` / `review-pr` exit codes + artifact validity |

## Start local runtime

No server — Cerberus is a CLI. Build once, then drive the binary.

```sh
# deterministic gate (run first; writes evidence to target/cerberus/)
./scripts/verify.sh

# build the binary for ad-hoc runs
cargo build -q            # → target/debug/cerberus  (or: cargo run -q -- <args>)
```

- Env for a LIVE review: `OPENROUTER_API_KEY` (already in the agent env from
  `op://Agents`). Pass it through explicitly with `--allow-env OPENROUTER_API_KEY`.
- Model: `openrouter/z-ai/glm-5.2` is the proven review model (see `_done/006`).
- Everything deterministic runs offline against `fixtures/`.

## Fixture QA (machinery — fast, offline)

1. `./scripts/verify.sh` and confirm EXIT=0.
2. Open a produced artifact (`target/cerberus/artifact.json`) and its rendered
   markdown (`target/cerberus/review.md`) — check the artifact is valid
   `ReviewArtifact.v1` and the render reads correctly. Exit code alone is a weak
   oracle.
3. If you touched validation, add/point at the fixture that would fail without
   your change (`fixtures/harness/invalid-*.txt`) and confirm it still catches.

## Live review QA (the brain — the part tests can't fake)

Do this for any `prompt.rs` / `review_doctrine.md` / model / context change.

```sh
# review a real diff on this repo, dry-run (writes an artifact, posts nothing)
cargo run -q -- review-pr --number <PR> --repo misty-step/cerberus \
  --model openrouter/z-ai/glm-5.2 --allow-env OPENROUTER_API_KEY \
  --harness opencode --timeout-seconds 1800 \
  --out-dir target/cerberus/qa-live --dry-run
```

Then **read the artifact and transcript by hand** — this is the QA, not the run:

1. Is every finding's **claim** true (not merely its anchor valid)? Open the
   cited lines.
2. Did the transcript show real exploration (git/grep/ast-grep beyond the diff),
   or did it stop at the diff?
3. Signal > noise: a few high-conviction findings beat a wall of nits. Did the
   change move it the right way (e.g. a doctrine change should catch a real smell
   it missed before — verify against a diff you KNOW has one)?
4. Clean diff → does it correctly return `PASS` with empty findings, not invented
   issues?

Note the boundary: **scored** faithfulness (paired baseline-vs-candidate, CIs,
judge κ) is Threshold's arena, not this repo (`backlog.d/020`, `_done/015`). This
skill is the human-read smoke that precedes that arena.

## Post-path QA (idempotency)

```sh
cargo run -q -- review-pr --number <PR> --repo misty-step/cerberus \
  --harness fixture --fixture-output fixtures/harness/valid-review.txt \
  --out-dir target/cerberus/qa-post --summary-target check-run --post
# run the exact command again on the frozen-head PR:
```

Second run must **update** the summary + inline comments (PATCH), not duplicate
them. Confirm on the PR.

## Gotchas

- **verify.sh green says nothing about review quality.** Fixtures are canned. A
  reviewer regression passes the whole gate. Live-review any brain change.
- **Untrusted-PR key exfil** — a live review runs a model with the shell in the
  checkout; only run live against trusted PRs (`_done/013` / container isolation).
- **Idempotency is easy to break silently** — always run the post twice.
- Live runs cost tokens and take ~2 min; don't loop them, read the one artifact.

## Report

Return: **verdict** (PASS / FAIL / UNVERIFIED) · exact commands run · surfaces
exercised (machinery vs brain) · artifacts inspected (paths under
`target/cerberus/`) · for a brain change, the human groundedness read · what was
NOT covered (e.g. "no live review — fixture only") and whether Threshold scoring
is owed.
