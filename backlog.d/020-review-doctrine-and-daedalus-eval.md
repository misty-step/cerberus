# Review doctrine in the prompt + prove it via a Daedalus arena run

Priority: P1 · Status: ready · Estimate: S (Cerberus side shipped) + Daedalus pull

## Goal
The master-reviewer prompt now carries an explicit **review doctrine** — the
"what to hunt" vocabulary (plausible-but-wrong model-code failure modes, Fowler's
*Refactoring* Ch.3 smell vocabulary as judgement calls, and a structural-ambition
bar). Shipped in `src/review_doctrine.md`, embedded into both `build_master_prompt`
and `build_opencode_message` via `include_str!`, pinned by
`prompt::tests::prompts_embed_review_doctrine`. This ticket tracks the *measurement*
of that change, which by the locked boundary is Daedalus's surface — not in-repo.

## Why
Before this change the production reviewer's doctrine was thinner than Harness
Kit's interactive `/code-review` lens bench: it said "prioritize correctness,
security, behavior regressions over style" but carried none of the smell
vocabulary that makes an LLM reviewer sharp. Fowler's smell *names* are dense in
pretraining (catnip), so naming them in the prompt is high-leverage, low-token.
The doctrine is distilled from `harness-kit/harnesses/shared/references/lenses.md`
(the `fowler`, `thermo-nuclear`, and plausible-but-wrong material) so the two
review surfaces share one doctrine.

## Cross-repo sync (drift risk — read before editing)
`src/review_doctrine.md` is a **distilled mirror** of the Harness Kit lens bench.
Source of truth is `harness-kit/harnesses/shared/references/lenses.md`. Edit the
bench there first, then mirror the distilled subset here. There is no automated
sync today; if this mirror drifts often, add a check (or a generator) rather than
trusting discipline. Kept as runtime *vocabulary*, not fixed personas — Cerberus
still designs any lane from the diff at runtime (`prompt.rs` mission rules hold).

## Oracle (Daedalus-owned, per 015 closure + VISION "Not an evaluation lab")
- [ ] Daedalus runs its review-autoresearch arena over Cerberus receipts with two
      paired harness configs: **baseline** = the pre-doctrine prompt, **candidate**
      = doctrine-on (this change), same model/substrate/corpus.
- [ ] Faithfulness / false-confident rate reported **with a confidence interval**,
      paired baseline-vs-candidate, sample sized to the effect.
- [ ] Judge calibrated to human labels (Cohen's κ) before its scores are trusted.
- [ ] Accept the doctrine only if it moves the score **outside the noise floor**
      and does **not** inflate false-confident findings (more real smells caught,
      not more noise). A delta inside the CI is not a result — revert or revise.

## Boundary notes
- `_done/015-measure-improve-review-faithfulness.md`: eval lab = Daedalus; Cerberus
  emits `ReviewReceiptBundle.v1` (shipped in `_done/005`) and owns reviewer quality
  (prompt/context/substrate) — exactly the lever this change pulls.
- Factory lane note, 2026-07-01: the measurement path is the Crucible/Threshold
  review-quality eval (factory backlog 020/054). Cerberus should keep emitting
  request/artifact/receipt evidence that that arena can consume; it should not
  grow an in-repo scorer, leaderboard, or promotion loop.
- If the arena surfaces a missing receipt field needed to score the doctrine, that
  becomes a small concrete Cerberus ticket *pulled by Daedalus*.

## Done when
- [x] Doctrine asset + prompt wiring + embed test shipped; `verify.sh` green.
- [ ] Daedalus arena verdict recorded (keep / revise / revert) with CI + κ.
