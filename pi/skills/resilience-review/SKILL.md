---
name: resilience-review
description: Resilience/failure-mode checklist for Cerberus fuse reviewer. Use when validating behavior under dependency and infrastructure failure.
---

# Resilience Focus

Prioritize failure containment:
- missing timeouts/retries/circuit boundaries
- retry storms and backpressure collapse risks
- fallback correctness and stale-data safety
- idempotency and partial-failure recovery gaps

Show trigger → blast radius → mitigation path.
