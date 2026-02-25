---
name: security-review
description: Security threat-model checklist for Cerberus guard reviewer. Use when tracing exploit paths and trust-boundary violations.
---

# Security Focus

Prioritize exploitable paths:
- injection sinks, authz gaps, data exposure
- unsafe shell/file/network handling with untrusted input
- missing validation where attacker impact is plausible
- secret leakage in logs/config/runtime output

Require input → sink → impact evidence chain.
