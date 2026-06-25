# Measure & improve review faithfulness via evals + harness

Priority: P0 · Status: closed (redirected to Daedalus) · Estimate: XL · Closed: 2026-06-25

## Disposition: closed — redirected to Daedalus, not built in Cerberus

This ticket's oracle — a versioned golden corpus, an LLM-as-judge faithfulness
scorer with confidence intervals, judge calibration (Cohen's κ), and a
keep/discard harness-iteration loop — is **Daedalus's owned surface**, not
Cerberus's. Building it here would duplicate Daedalus and contradict the locked
boundary:

- `spec.md` §External Evals: "Cerberus does not own model or harness evaluation…
  Daedalus and other upstream laboratories may evaluate Cerberus… Cerberus only
  needs enough receipt [surface]." That surface is `ReviewReceiptBundle.v1`,
  **already shipped in `_done/005`**.
- `VISION.md`: Cerberus is "Not an evaluation lab" — no leaderboards,
  harness-vs-harness matrices, reviewer-config promotion, eval dashboards, or
  long-lived benchmark storage.
- Daedalus `docs/048-cerberus-rd-lab-context.md`: "Cerberus owns
  `ReviewRequest.v1 → ReviewArtifact.v1`, artifact validation, context-capability
  truth, and harness receipts. **Daedalus owns arenas, frozen evals,
  candidate/run records, analysis, Pareto/reporting, and sandbox-only promotion
  logic.**" Daedalus already runs the review autoresearch loop
  (`docs/review-autoresearch-loop.md`) over Cerberus receipts.
- **Operator decision, 2026-06-25:** keep the split — Cerberus is 100%-focused on
  being the best code-review agent (beat Greptile/CodeRabbit); Daedalus is the
  research/eval engine. The split may be revisited later (Cerberus-specific
  code-review evals could move in-repo), so this closure is *for now*, not dogma.

## The legitimate residue stays in Cerberus — already ticketed

The trustworthy-review *outcome* behind this ticket is pursued through
Cerberus-owned, oracle-decidable work, not an in-repo eval lab:

- **007** — citation/anchor *resolution* (the deterministic faithfulness floor a
  non-AI oracle can decide, per ADR 0003).
- **008** — pin the untested safety guards with regression tests.
- **009** — operator visibility + actionable errors.
- Being an excellent reviewer (prompt / context / substrate quality) — the lever
  Daedalus measures and recommends.

If Daedalus's arena later hits a concrete Cerberus gap (a missing receipt field,
or a harness knob it needs to sweep), that becomes a small, concrete Cerberus
ticket *pulled by Daedalus* — not a speculative in-repo eval build.

---

## Original ticket (preserved for the record)

### Goal
Make Cerberus's reviews trustworthy the way the bitter lesson demands — measure
faithfulness and iterate the *agent*, not hand-code a Rust verifier for it. This
is the actual trust moat VISION names ("trust earned by low false-confident rate,
measured").

### Non-Goals
- No deterministic Rust "groundedness gate" for semantic faithfulness (ADR 0003 — a gameable proxy).
- Cerberus is not the eval *lab* (Daedalus scores); Cerberus emits the corpus + receipts and runs the harness-iteration loop.

### Oracle
- [ ] A versioned golden corpus: N labeled real PRs with human-judged expected findings (true issues + known non-issues / traps).
- [ ] A faithfulness / false-confident scorer (LLM-as-judge vs the labeled baseline) reporting precision and false-confident rate **with a confidence interval**, paired against a baseline harness config.
- [ ] A harness-iteration loop: a prompt/context/model/tool change is accepted only if it moves the score outside the noise floor on the corpus (sample sized to the effect).
- [ ] The judge is calibrated against human labels (report Cohen's κ) before its scores are trusted.

### Verification System
- Claim: a harness change that improves review faithfulness shows a measurable score gain on the golden corpus, paired vs baseline, outside the confidence interval.
- Falsifier: scores move inside the noise floor (under-powered sample); or the judge disagrees with human labels (low κ) so its verdicts are noise.
- Driver: an `eval` run over the corpus; paired baseline-vs-candidate harness configs.
- Grader: LLM-as-judge calibrated to human labels; precision / false-confident with CIs.
- Evidence packet: the corpus, per-config scores + CIs, the judge-vs-human calibration.
- Cadence: on every harness change; tracked over time; feeds the Daedalus handoff.

### Notes
**Why:** ADR 0003 + research. Open-ended quality is judged by models + evals across the literature (MT-Bench/G-Eval; FActScore/RAGAS for faithfulness), never by hand-crafted verifiers (which Goodhart). Subsumes 006's "measure artifact-validity rate over N runs" follow-on. This is "configure the agent + measure" — the bitter-lesson-aligned moat that turns harness engineering (prompt/model/context) into a disciplined loop instead of vibes. The single highest-leverage ticket for making the verdict trustworthy enough to gate on.

> Closure note: the "runs the harness-iteration loop" clause above is exactly the
> part that belongs to Daedalus's autoresearch loop, not Cerberus. That tension is
> why this ticket was closed rather than built.
