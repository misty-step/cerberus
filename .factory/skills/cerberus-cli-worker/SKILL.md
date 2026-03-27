---
name: cerberus-cli-worker
description: Implement CLI-only Cerberus refactor features with TDD, terminal verification, and aggressive legacy-surface retirement.
---

# Cerberus CLI Worker

NOTE: Startup and cleanup are handled by `worker-base`. This skill defines the work procedure for Cerberus CLI migration features.

## When to Use This Skill

Use this skill for features that:

- change the `cerberus review --repo --base --head` flow
- refactor or simplify the Elixir review core
- implement merged reviewer configuration or planner behavior
- remove legacy GitHub/API/Sprite/Node/shell surfaces
- move the Elixir app to repo root
- finalize the packaged CLI artifact

## Required Skills

- `cerberus-terminology` — invoke before substantive terminology, reviewer-vocabulary, prompt, or config-naming changes. Routine flag/help-text adjustments that do not introduce or rename Cerberus concepts do not require it.

## Work Procedure

1. Read the assigned feature, `mission.md`, mission `AGENTS.md`, `validation-contract.md`, repo `AGENTS.md`, and the relevant `.factory/library/*.md` files before editing anything.
2. Invoke `cerberus-terminology` only when the feature changes substantive user-facing nouns, reviewer/config vocabulary, or prompt wording. For large structural refactors, create characterization tests first, move one boundary at a time, and delete legacy surfaces only after the replacement path is green.
3. Inspect the current code/tests for the touched surface and decide the smallest characterization/failing tests needed to pin behavior before implementation.
4. Add or update tests first (red). For planner/config features, use deterministic doubles and fixed fixture repos/ref ranges. For cleanup features, add tests or assertions that fail until the legacy surface is actually removed or the root move is complete.
5. Implement in small cohesive steps. Keep the product CLI-only:
   - no HTTP API/server path
   - no Sprite/Fly runtime
   - no GitHub Action bootstrap
   - no new long-running services or port requirements
6. Run targeted tests after each meaningful step. Keep evidence for:
   - resolved refs/workspace behavior
   - resolved config snapshots/diffs
   - planner traces
   - reviewer execution ledgers
   - terminal transcripts for invalid input and success paths
7. Perform manual terminal verification for the feature’s user-visible contract. Examples:
   - `cerberus review --help`
   - invalid args / bad repo / bad refs
   - paired fixture review runs
   - override-driven reruns
   - packaged CLI run outside the source tree
8. Run broader validators before handing off:
   - feature-relevant targeted tests
   - `.factory/services.yaml` commands for `compile`, `test`, `format`, and `package` when relevant
   - `legacy-surface-sanity` only while legacy files still exist
9. Keep git-mutating fixtures and other test-only helpers out of runtime `lib/` paths unless runtime packaging truly requires them; if an exception is necessary, explain it explicitly in the handoff.
10. Do not leave background processes or temp services running. If you create fixture repos, worktrees, or packaging artifacts, clean them up unless the feature explicitly needs them to persist in-repo.
11. In the handoff, be explicit about what changed, what was verified, what was left undone, and any structural risks discovered.

## Example Handoff

```json
{
  "salientSummary": "Replaced the diff-file CLI contract with `--repo --base --head` workspace preparation, rejected legacy `--diff`, and added deterministic empty-range + invalid-ref handling. Targeted CLI/workspace tests pass and manual terminal checks confirmed no caller worktree mutation.",
  "whatWasImplemented": "Added request/workspace preparation for local ref ranges, updated the CLI parser/help text to the canonical ref-based surface, removed legacy `--diff` handling, and added tests/fixtures that prove cwd independence, no-change behavior, invalid repo/ref diagnostics, and no mutation of the caller checkout or worktree list.",
  "whatWasLeftUndone": "",
  "verification": {
    "commandsRun": [
      {
        "command": "cd /Users/phaedrus/Development/cerberus-mono/cerberus/cerberus-elixir && mix test test/cerberus/cli_test.exs test/mix/tasks/cerberus_review_test.exs",
        "exitCode": 0,
        "observation": "Ref-based CLI parser and invalid-input coverage passed with the new fixtures."
      },
      {
        "command": "cd /Users/phaedrus/Development/cerberus-mono/cerberus/cerberus-elixir && mix test test/cerberus/local_repo_read_handler_test.exs",
        "exitCode": 0,
        "observation": "Workspace/repo-read tests passed, including traversal protection and cwd independence checks."
      }
    ],
    "interactiveChecks": [
      {
        "action": "Ran `mix cerberus.review --help`",
        "observed": "Help output advertised only `--repo`, `--base`, and `--head`; legacy `--diff` was absent."
      },
      {
        "action": "Ran a fixture review from outside the target repo, then compared branch/status/worktree-list before and after",
        "observed": "Review succeeded for the requested refs and the caller checkout/worktree list remained unchanged."
      }
    ]
  },
  "tests": {
    "added": [
      {
        "file": "cerberus-elixir/test/cerberus/cli_test.exs",
        "cases": [
          {
            "name": "review/1 resolves refs inside --repo from any cwd",
            "verifies": "CLI uses the requested repository for ref resolution and review context."
          },
          {
            "name": "review/1 rejects legacy --diff input",
            "verifies": "Legacy diff-file review input fails fast with actionable diagnostics."
          }
        ]
      }
    ]
  },
  "discoveredIssues": [
    {
      "severity": "medium",
      "description": "The current release contract still assumes repo-root asset copying; packaging choice will need a dedicated follow-up feature.",
      "suggestedFix": "Handle packaging only after the merged config/prompt asset loading path is self-contained."
    }
  ]
}
```

## When to Return to Orchestrator

- Packaging choice (`escript` vs release) forces a mission-level tradeoff the current feature cannot safely decide alone
- The supported override surface is too ambiguous to implement without changing mission scope
- Deterministic provider doubles or fixture repos needed for validation do not exist and require broader planning
- Root lift or legacy-surface deletion reveals hidden external dependencies, generated files, or CI assumptions that materially change scope
- A feature appears to require preserving GitHub/API/Sprite/server behavior to proceed
