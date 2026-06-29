# Cerberus repo contracts

- North star: read `VISION.md` before changing review scope, artifact shape,
  reviewer topology, caller boundaries, or runtime/substrate assumptions.
- Product contract: `spec.md` is the locked MVP contract. Architectural
  decisions live in `docs/adr/`.
- Cerberus is the opinionated code-review harness. It accepts arbitrary review
  context, usually a base/head diff, and produces a validated
  `ReviewArtifact.v1` that can stand alone or be projected into GitHub.
- Keep the core caller-neutral. Local runs, CI, GitHub Actions, Olympus,
  Bitterblossom, or another plane may trigger Cerberus; none of those should
  become the product boundary.
- The master reviewer may choose dynamic subagent lanes at runtime. Do not
  hardcode a static persona fleet into Rust.
- Review quality improves through evals and receipts. Cost, model choice,
  prompt shape, tool access, and subagent topology are optimization variables,
  not constants to hide in product code.

## Gate

Run before claiming repo changes are complete:

```sh
./scripts/verify.sh
```

For docs-only changes, still run the gate unless the failure is an unrelated
environment issue; report the exact command and residual risk.
