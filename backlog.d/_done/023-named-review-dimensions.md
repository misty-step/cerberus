# Name the review dimensions the master must consider

Priority: P1 | Status: done (2026-07-02) | Estimate: M | Factory epic: 2

## Goal

Give the Cerberus master an explicit, versioned set of review dimensions it must
consider while preserving the core product rule: Rust does not hardcode a static
persona fleet, and the master still chooses the right reviewer topology at
runtime.

The mandatory new dimension is:

`heuristic-where-a-model-belongs-and-model-where-deterministic-code-belongs`

That means every review should ask both questions:

- Did this change replace judgment, semantic classification, realtime, speech,
  vision, agentic capability, or other model-native product behavior with
  brittle keyword heuristics?
- Did this change add model calls where deterministic code should own scoring,
  policy, persistence, security, or other oracle-checkable behavior?

## Oracle

- [x] The master prompt/review doctrine names the dimension above in plain
      language and treats it as mandatory review vocabulary. Added a
      "Model-boundary judgment (mandatory dimension...)" section to
      `src/review_doctrine.md`, which both prompt surfaces already embed
      verbatim and unconditionally — no new gating needed.
- [x] The prompt still tells the master to compose lanes dynamically from the
      diff; no static correctness/security/architecture persona roster appears
      in Rust. Unchanged — this is doctrine *vocabulary* text, same shape as
      the existing Fowler-smells/plausible-but-wrong sections, not a persona.
- [x] Artifacts or receipts record enough reviewer-planning context to show
      which dimensions were considered without making validation depend on a
      subjective model-quality judgment. Added `review_doctrine_digest`
      (sha256 of `review_doctrine.md`) to `ReviewReceiptBundle.v1` — a
      content-derived fact, not a self-reported model claim. Live-verified in
      `target/cerberus/receipts/opencode.json` during `./scripts/verify.sh`.
- [x] A fixture or prompt regression test proves the dimension remains present
      in both `build_master_prompt` and the OpenCode message path.
      `prompt::tests::prompts_embed_review_doctrine` now asserts the exact
      dimension name string in both prompts; `receipt::tests::receipt_bundle_records_the_review_doctrine_digest`
      pins the digest.
- [x] `./scripts/verify.sh` passes.

## Children

1. **Done.** Added the named dimension to `src/review_doctrine.md`; both
   prompt surfaces embed the shared doctrine text already, so no separate
   prompt-contract edit was needed.
2. **Done.** Recording surface: `ReviewReceiptBundle.v1.review_doctrine_digest`
   (receipt metadata, per the ticket's own preference — no caller branches on
   it, it's audit evidence).
3. **Partially done — regression coverage yes, a new fixture transcript no.**
   Added prompt regression coverage (see Oracle above). Did not add a
   separate fixture *transcript* demonstrating an invoked finding: the shared
   canonical fixture (`fixtures/harness/valid-review.txt`) is depended on by
   many `verify.sh` assertions on exact finding/category content, so editing
   it for a purely illustrative purpose carried real regression risk for no
   functional gain — `Finding.category` is already a free-form string, so no
   schema or code change was needed to let a real review use this dimension's
   vocabulary in a finding; the doctrine text reaching every prompt
   unconditionally already proves it "can be invoked."

## Notes

This is review vocabulary, not a rule engine. Deterministic Rust may require the
dimension to be considered and recorded; it must not pretend to score whether
the reviewer's judgment was good without an external eval.
