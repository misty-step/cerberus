---
name: reviewer-delta-triage
description: |
  Compare Cerberus against other AI reviewers on a single PR, classify each external finding as a real Cerberus miss or noise, and append a structured entry to the triage log. Use when a PR has comments from Greptile, CodeRabbit, Gemini, Codex, Claude, or similar reviewers and you need to judge whether Cerberus was blind, skipped, or correctly passed.
---

# Reviewer Delta Triage

One PR in, one log entry out. The value compounds across runs — miss patterns that repeat become hardening work.

## Workflow

1. **Collect** the PR review surface using the collector script.
2. **Verify channel coverage.** GitHub stores review feedback in three separate channels.
   ALL THREE are required before you can proceed:
   - **PR comments** (`comments`) — top-level conversation
   - **Review bodies** (`reviews`) — summary text submitted with a review
   - **Inline review comments** (`review_comments`) — line-level comments on specific files

   The collector fetches all three. After running it, check the stderr summary line:
   `Collected: N comments, N reviews, N inline review comments, N authors`

   **If `review_comments` is missing or 0 and external reviewers are present, STOP.**
   Fetch manually: `gh api repos/{owner}/{repo}/pulls/{pr}/comments --paginate`
   Most actionable findings from Gemini, Codex, and CodeRabbit are inline review comments.
   Skipping this channel silently drops the majority of external signal.

3. **Read every comment body** from every channel, every reviewer. Count findings per reviewer
   before classifying — if an external reviewer has a review body but zero inline comments,
   that is suspicious (Gemini/Codex almost always post inline).
4. **Read the diff and touched code** — you cannot judge findings without seeing what was actually written.
5. **Identify Cerberus's lane**: which perspectives ran, which timed out, what the verdict was.
6. **Classify every external finding** (see Judgment Rules).
7. For every real miss, **tag the perspective** that should have caught it + the improvement lever.
8. **Append a structured entry** to `.groom/triage-log.md` (see Log Format).
9. **Print a short summary** to the conversation.

## Judgment Rules

- Treat external reviewer comments as hypotheses, not truth. Verify against the diff.
- Do not count "Cerberus missed it" when Cerberus timed out or never ran — that's **impaired**, not **blind**.
- Do not count stylistic nitpicks as recall failures unless they point to a real defect.
- A reviewer being more cautious is not automatically "better."
- Distinguish three states:
  - **blind**: Cerberus ran that perspective and should have flagged it.
  - **impaired**: Cerberus skipped, timed out, or lacked the right reviewer/model.
  - **noise**: the external comment is technically weak, misleading, or below Cerberus's bar.
- When an external finding is valid but minor, prefer hardening evals/prompts over changing verdict thresholds.
- Credit Cerberus when it finds things external reviewers missed — that's signal too.

## Log Format

Append one entry per PR to `.groom/triage-log.md`. Each entry follows this structure exactly:

```markdown
---

### PR #<number> — <title>

**Date:** YYYY-MM-DD | **Link:** <url> | **Verdict:** <PASS|WARN|FAIL>
**Ran:** <perspective (status)>, ... | **Timed out:** <perspective>, ... | **Skipped:** <perspective>, ...

#### Misses

| Finding | Category | Perspective | Blind/Impaired | Found by | Lever |
|---------|----------|-------------|----------------|----------|-------|

If no real misses: "None — Cerberus covered all real findings."

#### Cerberus-only finds

Findings Cerberus caught that no external reviewer flagged.

| Finding | Perspective | Category |
|---------|-------------|----------|

If none: "None."

#### Noise

External findings classified as overscrupulous, incorrect, or below bar.

| Finding | Reviewer | Why noise |
|---------|----------|-----------|

#### Signal quality

| Reviewer | Findings | Real | Noise | Unique (not found by others) |
|----------|----------|------|-------|------------------------------|

#### Patterns

Bullet list of recurring themes worth watching across future runs. Tag with perspective.
```

### Rules for the log

- Append only. Never edit prior entries.
- Every entry must include the PR link.
- Keep findings to one line each — title-level summary, not full description.
- Tag every miss with exactly one perspective and one lever.
- Lever values: `prompt`, `context`, `routing`, `model/timeout`, `eval`, `severity-policy`.
- If the log file doesn't exist yet, create it with a header.

## Collector

```bash
python3 .claude/skills/reviewer-delta-triage/scripts/collect_pr_review_surface.py \
  --repo misty-step/cerberus \
  --pr <number> \
  --out /tmp/pr-<number>-review-surface.json
```

The collector prints a channel summary to stderr. Verify all three channels have data.

## What this skill does NOT do

- Open GitHub issues. That happens when the same miss pattern appears 3+ times in the log.
- Change prompts or evals directly. It logs the signal; a separate pass acts on it.
- Replace reading the actual PR comments. The collector is a convenience, not a substitute.
