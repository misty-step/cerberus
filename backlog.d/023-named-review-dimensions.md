# Name the review dimensions the master must consider

Priority: P1 | Status: ready | Estimate: M | Factory epic: 2

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

- [ ] The master prompt/review doctrine names the dimension above in plain
      language and treats it as mandatory review vocabulary.
- [ ] The prompt still tells the master to compose lanes dynamically from the
      diff; no static correctness/security/architecture persona roster appears
      in Rust.
- [ ] Artifacts or receipts record enough reviewer-planning context to show
      which dimensions were considered without making validation depend on a
      subjective model-quality judgment.
- [ ] A fixture or prompt regression test proves the dimension remains present
      in both `build_master_prompt` and the OpenCode message path.
- [ ] `./scripts/verify.sh` passes.

## Children

1. Add the named dimensions to `src/review_doctrine.md` and the prompt contract.
2. Decide the smallest durable recording surface: receipt metadata, artifact
   run metadata, or a sidecar reviewer-plan receipt. Prefer receipt metadata
   unless a caller must branch on it.
3. Add prompt regression coverage and one fixture review transcript that shows
   the dimension can be invoked without hardcoding a reviewer persona.

## Notes

This is review vocabulary, not a rule engine. Deterministic Rust may require the
dimension to be considered and recorded; it must not pretend to score whether
the reviewer's judgment was good without an external eval.
