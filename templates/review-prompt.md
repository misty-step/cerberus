Review this pull request from your specialized perspective.

## PR Context
- **Title:** {{PR_TITLE}}
- **Author:** {{PR_AUTHOR}}
- **Branch:** {{HEAD_BRANCH}} → {{BASE_BRANCH}}
- **Description:**
{{PR_BODY}}

## Changed Files
{{FILE_LIST}}

## Diff
{{DIFF}}

## Scope Rules
- ONLY flag issues in code that is ADDED or MODIFIED in this diff.
- You MAY read surrounding code for context, but do not report issues in unchanged code.
- If an existing bug is made worse by this change, flag it. If it was already there, skip it.
- Do not suggest improvements to code outside the diff.

## Instructions
1. Read the diff carefully.
2. Use your tools to investigate the repository — read related files, trace imports, understand context.
3. Apply your specialized perspective rigorously.
4. Produce your structured review JSON at the END of your response.
5. Be precise. Cite specific files and line numbers from the diff.
6. If you find nothing actionable, say so clearly and PASS.
