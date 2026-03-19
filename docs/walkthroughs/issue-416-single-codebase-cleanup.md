# Issue #416 Walkthrough: active dogfood config excludes archived repos

## Summary

This lane finishes the remaining in-repo single-codebase cleanup by removing archived repos from active dogfood config and codifying the archive boundary in one place.

- `defaults/dogfood.yml` now lists only active core repos
- the config declares `archived_repos` explicitly for ADR 005 policy
- `scripts/check-dogfood-presence.py` rejects any overlap between active and archived repo sets
- `tests/test_dogfood_presence.py` locks the active repo set and the archive boundary

## Before

- `defaults/dogfood.yml` still treated `misty-step/cerberus-cloud` as an active dogfood target
- archive policy was implicit, so future edits could reintroduce archived repos without a clear guardrail
- the issue's grep-based cleanup claim was not true for active config

## After

- active dogfood targets are `misty-step/cerberus`, `misty-step/volume`, and `misty-step/gitpulse`
- archived repos live under a dedicated `archived_repos` list
- config loading fails fast if an archived repo is reintroduced into `core_repos`
- remaining `cerberus-cloud` / `cerberus-web` hits are historical benchmark or ADR context, or the new regression guardrails

## Verification

Persistent verification for this path:

```bash
python3 -m pytest tests/test_dogfood_presence.py -q
make validate
timeout 15s rg -n "cerberus-cloud|cerberus-web" .
```

## Why This Is Better

The important change is not just deleting one stale repo name. The config, loader, and tests now share one explicit rule: archived repos are historical context, not live operational targets. That makes the single-codebase decision mechanically enforceable instead of relying on memory.
