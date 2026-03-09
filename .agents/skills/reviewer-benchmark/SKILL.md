---
name: reviewer-benchmark
description: |
  Compare Cerberus against other AI code reviewers on recent GitHub pull requests, build a dated scorecard, and turn misses into concrete Cerberus hardening work. Use when auditing the last 7-10 days of PRs, evaluating reviewer composition, grading Cerberus recall against CodeRabbit, Greptile, Gemini, Claude, or Codex, or producing the recurring reviewer benchmark for this repository.
---

# Reviewer Benchmark

Produce a recurring cross-reviewer audit for Cerberus and convert it into durable backlog pressure.

## Workflow

1. Collect the recent PR review corpus with `scripts/collect_pr_reviews.py`.
2. Prioritize repos with the most review signal and any repos explicitly named by the user.
3. Read both issue comments and review bodies. For Cerberus, key on `<!-- cerberus:verdict -->` comments first.
4. Separate findings into:
   - Cerberus unique catches
   - Cerberus misses
   - overlap / reinforcement
   - coverage gaps, skips, or missing-reviewer cases
5. Translate misses into improvement hypotheses across prompts, context retrieval, reviewer architecture, model routing, timeout policy, and eval coverage.
6. Write the report using `references/report-template.md` into `docs/reviewer-benchmark/YYYY-MM-DD-*.md`.
7. Update `docs/BACKLOG-PRIORITIES.md` when the run changes active Cerberus hardening priorities.
8. Raise `--limit` or `--repo-limit` when the org or review window is large enough to risk truncation warnings.

## Output Rules

- Use exact dates and PR identifiers.
- Distinguish:
  - Cerberus absent
  - Cerberus skipped
  - Cerberus present but low-signal
  - Cerberus present and uniquely useful
- Treat `chatgpt-codex-connector` as separate from Cerberus.
- Do not merge "Cerberus missed it" and "Cerberus never ran" into the same bucket.
- Prefer high-signal examples over exhaustive low-signal comment paraphrases.

## Commands

Collect the full org corpus:

```bash
python3 .agents/skills/reviewer-benchmark/scripts/collect_pr_reviews.py \
  --org misty-step \
  --since 2026-03-01 \
  --out /tmp/misty-step-pr-reviews.json
```

Collect a smaller repo subset:

```bash
python3 .agents/skills/reviewer-benchmark/scripts/collect_pr_reviews.py \
  --org misty-step \
  --since 2026-03-01 \
  --repo misty-step/cerberus \
  --repo misty-step/cerberus-cloud \
  --repo misty-step/volume \
  --out /tmp/misty-step-core-reviews.json
```

## Resources

- Report template: `references/report-template.md`
- Collection script: `scripts/collect_pr_reviews.py`
- Collector output: top-level metadata plus `repos`, where each repo entry maps to `{ "pull_requests": [...], "error": null | "...", "truncated": bool }`
