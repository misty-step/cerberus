# Measure & improve review faithfulness via evals + harness

Priority: P0 · Status: pending · Estimate: XL

## Goal
Make Cerberus's reviews trustworthy the way the bitter lesson demands — measure faithfulness and iterate the *agent*, not hand-code a Rust verifier for it. This is the actual trust moat VISION names ("trust earned by low false-confident rate, measured").

## Non-Goals
- No deterministic Rust "groundedness gate" for semantic faithfulness (ADR 0003 — a gameable proxy).
- Cerberus is not the eval *lab* (Daedalus scores); Cerberus emits the corpus + receipts and runs the harness-iteration loop.

## Oracle
- [ ] A versioned golden corpus: N labeled real PRs with human-judged expected findings (true issues + known non-issues / traps).
- [ ] A faithfulness / false-confident scorer (LLM-as-judge vs the labeled baseline) reporting precision and false-confident rate **with a confidence interval**, paired against a baseline harness config.
- [ ] A harness-iteration loop: a prompt/context/model/tool change is accepted only if it moves the score outside the noise floor on the corpus (sample sized to the effect).
- [ ] The judge is calibrated against human labels (report Cohen's κ) before its scores are trusted.

## Verification System
- Claim: a harness change that improves review faithfulness shows a measurable score gain on the golden corpus, paired vs baseline, outside the confidence interval.
- Falsifier: scores move inside the noise floor (under-powered sample); or the judge disagrees with human labels (low κ) so its verdicts are noise.
- Driver: an `eval` run over the corpus; paired baseline-vs-candidate harness configs.
- Grader: LLM-as-judge calibrated to human labels; precision / false-confident with CIs.
- Evidence packet: the corpus, per-config scores + CIs, the judge-vs-human calibration.
- Cadence: on every harness change; tracked over time; feeds the Daedalus handoff.

## Notes
**Why:** ADR 0003 + research. Open-ended quality is judged by models + evals across the literature (MT-Bench/G-Eval; FActScore/RAGAS for faithfulness), never by hand-crafted verifiers (which Goodhart). Subsumes 006's "measure artifact-validity rate over N runs" follow-on. This is "configure the agent + measure" — the bitter-lesson-aligned moat that turns harness engineering (prompt/model/context) into a disciplined loop instead of vibes. The single highest-leverage ticket for making the verdict trustworthy enough to gate on.
