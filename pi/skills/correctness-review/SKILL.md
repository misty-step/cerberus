---
name: correctness-review
description: Correctness/logic checklist for Cerberus trace reviewer. Use when validating behavioral correctness and bug risk.
---

# Correctness Focus

Prioritize execution-path bugs:
- boundary conditions, null/empty handling, branch completeness
- state transitions, ordering, race/concurrency hazards
- incorrect fallbacks and partial-failure logic
- data-flow invariants between producers and consumers

Report only concrete failing paths with exact evidence.
