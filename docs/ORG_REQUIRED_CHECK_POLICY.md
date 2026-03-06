# Org Required Check Policy

Default policy for `misty-step` repositories:

- Prefer one explicit aggregate gate: `merge-gate`
- Do not require generic names like `CI`, `check`, `test`, `build`, `lint`
- If a repo truly needs multiple required checks, they must be intention-revealing:
  - good: `quality-gates`, `docker`, `review / Cerberus`
  - bad: `CI`, `check`, `Test`
- If a workflow uses `workflow_run`, it must reference the workflow name, not the required check name
- When renaming a required check:
  1. update workflow/job names on default branch or every open PR branch
  2. then patch branch protection
  3. then verify PRs emit the new check

Use the audit tool to catch drift:

```bash
python3 scripts/audit-required-checks.py --org misty-step --flag-ambiguous
```

Migration rule:

- Existing repos may keep non-ambiguous explicit gates temporarily
- New repos should use `merge-gate` unless there is a repo-specific reason not to
