---
name: performance-review
description: Performance/scalability checklist for Cerberus flux reviewer. Use when analyzing hot paths and growth behavior.
---

# Performance Focus

Prioritize runtime scaling risks:
- hot-path complexity regressions
- N+1 I/O patterns and missing batching
- unbounded memory/queue growth
- blocking operations on critical async paths

Prefer measurable, high-impact findings over micro-optimizations.
