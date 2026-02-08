# Cerberus

Multi-agent AI PR review council. Five parallel reviewers. Single council verdict gates merge.

## Reviewers
- APOLLO: correctness + logic (find the bug)
- ATHENA: architecture + design (zoom out)
- SENTINEL: security + threat model (think like an attacker)
- VULCAN: performance + scalability (think at runtime)
- ARTEMIS: maintainability + DX (think like next developer)

## Key Paths
- action: `action.yml` (review) + `verdict/action.yml` (council) + `triage/action.yml` (auto-triage)
- config: `defaults/config.yml`
- agents: `agents/`
- system prompts: `agents/*-prompt.md`
- scripts: `scripts/`
- templates: `templates/review-prompt.md`
- consumer template: `templates/consumer-workflow.yml`
- tests: `tests/`
- CI: `.github/workflows/ci.yml`

## Output Schema (Reviewer JSON)
Each reviewer ends with a JSON block in ```json fences.

Required fields:
- reviewer, perspective, verdict, confidence, summary
- findings[] with severity/category/file/line/title/description/suggestion
- stats with files_reviewed, files_with_issues, critical, major, minor, info

Verdict rules:
- FAIL: any critical OR 2+ major
- WARN: exactly 1 major OR 3+ minor
- PASS: otherwise

## Override Protocol
Comment command: `/council override sha=<short-or-full-sha>`

Rules:
- reason required
- sha must match current HEAD
- actor requirements in `defaults/config.yml`
