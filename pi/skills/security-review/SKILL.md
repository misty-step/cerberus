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
- trusted-looking metadata such as titles and branch names reused downstream
- fail-open defaults or default posture changes that weaken security
- raw error leakage to logs, responses, prompts, or operator-visible output
- async side-effect failures that silently drop audit/policy/security writes
- serialization and public-route exposure of unsafe internal fields

Require input → sink → impact evidence chain.
