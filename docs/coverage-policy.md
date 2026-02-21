# Coverage Policy

Coverage floors are defined in [`coverage-policy.yml`](../coverage-policy.yml) at the repo root.

## How to Advance the Ratchet

1. Ensure current coverage meets the next target (run `pytest --cov=scripts`).
2. Edit `coverage-policy.yml` — bump `global_floor` to the next value in `ratchet_steps`.
3. Open a PR. CI enforces the new floor automatically.

No other CI files need to change.

## Current Policy

| Setting | Value | Description |
|---------|-------|-------------|
| `global_floor` | 70% | Minimum line AND branch coverage across all code |
| `patch_threshold` | 90% | Minimum coverage for new/changed lines on any PR |

## Ratchet History

| Floor | Status |
|-------|--------|
| 30% | ✓ initial |
| 45% | ✓ completed |
| 60% | ✓ completed |
| **70%** | ← **current** |
| 80% | next target |

## Enforcement

- **Global floor**: CI reads `global_floor` from `coverage-policy.yml` and checks both branch and line coverage from `coverage.xml`. Fails the build if either metric is below the floor.
- **Patch coverage**: On pull requests, `diff-cover` checks that new/changed lines are covered at `patch_threshold` (90%) using `--fail-under`. CI fails the job if patch coverage is below threshold and posts details in the PR coverage comment.
- **PR comment**: Every PR gets a coverage comment showing current metrics, ratchet progress, and patch coverage results.

## Adding a New Ratchet Step

When you're ready to raise the bar to 80%:

```yaml
# coverage-policy.yml
global_floor: 80   # ← change this one line
```

That's it. CI picks it up on the next push.
