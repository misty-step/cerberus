---
name: testing-review
description: Testing/coverage checklist for Cerberus proof reviewer. Use when validating behavior coverage and regression safety.
---

# Testing Focus

Prioritize coverage realism:
- changed branches without direct assertions
- missing edge/failure path tests
- over-mocking that hides integration behavior
- flaky/non-deterministic test patterns

Differentiate exercised code from asserted behavior.
