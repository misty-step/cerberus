---
name: cerberus-terminology
description: |
  Use when defining or revising Cerberus vocabulary, core concepts, reviewer/output terminology, glossary docs, prompt wording, or backlog language. Read the canonical terminology doc first and keep prompts, docs, issues, PRs, and walkthroughs aligned with the same nouns and verbs.
---

# Cerberus Terminology

Keep Cerberus language small, explicit, and stable.

## Workflow

1. Read `docs/TERMINOLOGY.md` first.
2. When editing prompts, docs, issues, PRs, or walkthroughs, prefer the glossary terms over ad hoc synonyms.
3. Treat a **finding** as a first-class reviewer claim.
4. Describe support with `evidence`, `citation`, `scope`, and `confidence` instead of inventing extra finding categories.
5. Delete or reject deprecated terminology aliases instead of preserving them as compatibility shims.
6. If a term is missing or overloaded, update `docs/TERMINOLOGY.md` before spreading new wording across the repo.
7. If terminology changes alter active work, align nearby backlog/issue/PR wording in the same lane.

## Terms To Avoid

- `verified finding`
- `unverified finding`
- vague substitutes like `warning-ish thing` or `signal`

## Preferred Pattern

- object first: `finding`, `verdict`, `reviewer`, `skip`, `override`
- support second: `evidence`, `citation`, `scope`, `confidence`
- action last: `emit`, `aggregate`, `gate`, `triage`, `remediate`

## Output Rule

When summarizing terminology work, report:

- glossary/doc changes
- prompt or schema wording changes
- backlog or issue alignment done
- any remaining vocabulary debt
