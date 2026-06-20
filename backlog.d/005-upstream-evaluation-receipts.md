# Emit upstream evaluation-ready receipts

Priority: P2 | Status: pending | Estimate: M

## Goal

Let Daedalus or another laboratory score real Cerberus runs without making
Cerberus own model or harness evaluation.

## Oracle

- [ ] Each review run can emit a stable receipt bundle with request digest,
  artifact digest, harness, model, latency, cost when available, capability
  tier, transcript URI, and validation outcome.
- [ ] Receipt bundles are redacted and deterministic enough for replay or
  scoring.
- [ ] A documented handoff format lets upstream labs compare harness/model
  candidates without changing Cerberus runtime behavior.

## Verification System

- Claim: Cerberus records enough structured evidence for external evaluators
  to score review quality, cost, latency, and degraded behavior.
- Falsifier: receipt bundles include secrets or private prompt paths; two runs
  with the same request cannot be matched by digest; model/cost/latency fields
  are missing from real OpenCode runs where the transcript includes them.
- Driver: fixture review, fake OpenCode/OMP review, and one optional real
  OpenCode smoke with explicit env allowlisting.
- Grader: JSON schema validation, redaction checks, and Daedalus import dry-run
  when available.
- Evidence packet: `target/cerberus/receipts/*.json`.
- Cadence: whenever harness receipt shape changes.

## Children

1. Define `ReviewReceiptBundle.v1` separate from `ReviewArtifact.v1`.
2. Add redaction tests for request files, prompt paths, env names, and
   transcript excerpts.
3. Parse available model/cost/usage metadata from OpenCode JSON events without
   depending on it for artifact validation.
4. Document Daedalus handoff expectations and import assumptions.

## Notes

**Why:** The accepted spec keeps model/harness evaluation outside Cerberus, but
ADR 0002 says Cerberus should record enough receipts for evaluators to score
runs. This is deliberately P2 until execution hardening and delivery loops are
in place.
