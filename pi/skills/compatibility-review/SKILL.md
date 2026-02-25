---
name: compatibility-review
description: Compatibility/contract checklist for Cerberus pact reviewer. Use when assessing client impact and version-skew safety.
---

# Compatibility Focus

Prioritize downstream break risk:
- wire format and API field semantic changes
- required/optional contract drift
- rollout ordering and rollback safety under skew
- migration/deprecation gaps for existing consumers

Flag concrete old-client failure modes with evidence.
