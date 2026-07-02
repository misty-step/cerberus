# Establish the review consistency floor before blocking gates

Priority: P1 | Status: ready | Estimate: M | Factory epic: 6

## Goal

Define and measure the consistency floor Cerberus must clear before any consumer
treats its verdict as a merge-blocking signal. Until that floor holds, every
deployment is advisory.

## Oracle

- [ ] Crucible owns the benchmark and records a Cerberus review-quality run with
      pass^k consistency over a seeded corpus and key-recall against adjudicated
      truth.
- [ ] The measured pass^k floor, sample size, confidence interval, and
      false-confident finding rate are recorded in a durable artifact linked
      from this ticket or from a child receipt.
- [ ] The blocking-gate threshold is explicit and higher than the current
      measured state. The groom report's live evidence records pass^5 near
      `0.0434`, which is not acceptable for blocking use.
- [ ] Cerberus producer manifests from `ReviewReceiptBundle.v1` are sufficient
      for Crucible to score production reviews without adding a leaderboard or
      scorer to Cerberus.
- [ ] Consumer docs and deployment wrappers state "advisory only" until the
      floor is met.

## Children

1. Pull `020-review-doctrine-and-threshold-eval.md` through the new Crucible
   benchmark path and record keep/revise/revert for the current review doctrine.
2. Add a periodic Crucible scoring run over production Cerberus receipts once
   Crucible's run database exists.
3. Define the minimum pass^k and false-confident-rate thresholds that reopen the
   blocking-gate question.
4. Add a small Cerberus-side receipt field only if Crucible proves it is needed
   to score production reviews.

## Notes

This epic closes the trust loop without making Cerberus an evaluation lab.
Cerberus emits artifacts and receipts; Crucible measures; consumers decide how
much authority to grant the result.
