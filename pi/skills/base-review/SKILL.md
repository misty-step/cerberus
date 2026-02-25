---
name: base-review
description: Structured Cerberus PR review workflow with machine-parseable JSON output and evidence-first findings. Use for every reviewer run.
---

# Base Review Workflow

## Objective
Produce one high-signal review with actionable findings and a final schema-valid JSON block.

## Required Workflow
1. Read the diff file path provided in the prompt.
2. Investigate changed files plus required nearby context.
3. Keep findings scoped to PR-introduced behavior (except defaults-change scope).
4. For each finding, include exact code evidence from the cited file/line.
5. Keep reviewer notes in `/tmp/<perspective>-review.md`.
6. End with exactly one fenced `json` block and nothing after it.

## Output Contract
- Use Cerberus severity set: `critical`, `major`, `minor`, `info`.
- Include complete `stats` fields.
- If blocked or incomplete, emit a `SKIP` verdict with a concise summary.
