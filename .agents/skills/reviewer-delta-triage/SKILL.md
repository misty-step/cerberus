---
name: reviewer-delta-triage
description: |
  Compare Cerberus against other AI reviewers on a single GitHub pull request, decide whether external findings are real Cerberus misses or low-signal noise, and turn valid misses into concrete hardening work. Use when a PR has comments from Greptile, CodeRabbit, Gemini, Codex, Claude, or similar reviewers and you need to judge whether Cerberus was blind, skipped, or correctly passed.
---

# Reviewer Delta Triage

Analyze one PR review surface and convert reviewer disagreement into a clear Cerberus improvement decision.

## Workflow

1. Collect the PR review surface with `.agents/skills/reviewer-delta-triage/scripts/collect_pr_review_surface.py`.
2. Read both issue comments and review bodies.
3. Identify the Cerberus lane first:
   - `PASS`
   - `WARN`
   - `FAIL`
   - `SKIP`
   - absent / did not run
4. Bucket every external reviewer finding into one of:
   - real Cerberus miss
   - useful note but non-blocking
   - low-signal / incorrect / overscrupulous
   - cannot judge from the comment alone
5. Verify the contested finding against the diff and touched code before judging Cerberus.
6. Decide the improvement lever for every real miss:
   - prompt contract
   - context retrieval
   - reviewer composition / routing
   - model choice / timeout policy
   - test / eval coverage
   - output formatting / severity policy
7. Produce a short report with:
   - disagreement summary
   - whether Cerberus was blind, skipped, or reasonably passed
   - concrete hardening actions
   - whether to open or update a Cerberus backlog item

## Judgment Rules

- Treat external reviewer comments as hypotheses, not truth.
- Do not count “Cerberus missed it” when Cerberus timed out or never ran.
- Do not count stylistic nitpicks as recall failures unless they would meaningfully improve the PR.
- A reviewer being more cautious is not automatically “better”; the question is whether the caution points to a real defect or useful note.
- Distinguish:
  - Cerberus blind: Cerberus ran and should have flagged it.
  - Cerberus impaired: Cerberus skipped, timed out, or lacked the right reviewer/model path.
  - External overscrupulousness: the external comment is technically weak, misleading, or below Cerberus’s intended bar.
- When an external finding is valid but minor, prefer hardening evals and prompts before changing verdict thresholds.

## Output Format

Use this shape in your response:

```md
## Verdict
- Greptile/Cerberus disagreement:
- Judgment:
- Why:

## Evidence
- External reviewer:
- Cerberus:
- Code reality:

## Hardening Work
- Needed:
- Lever:
- Concrete next change:
```

## Commands

Collect the current PR:

```bash
python3 .agents/skills/reviewer-delta-triage/scripts/collect_pr_review_surface.py \
  --repo misty-step/cerberus \
  --pr 383
```

Collect another PR and save it:

```bash
python3 .agents/skills/reviewer-delta-triage/scripts/collect_pr_review_surface.py \
  --repo misty-step/cerberus \
  --pr 383 \
  --out /tmp/pr-383-review-surface.json
```

## Resource

- Collector: `.agents/skills/reviewer-delta-triage/scripts/collect_pr_review_surface.py`
