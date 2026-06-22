# Enforce finding-groundedness and context-truth in Rust, not just the prompt

Priority: P0 · Status: pending · Estimate: L

## Goal
Make Cerberus's load-bearing trust invariant real: Rust rejects or quarantines any finding whose cited evidence does not resolve to content actually available at the artifact's declared context tier — so a confidently-wrong review cannot validate.

## Oracle
- [ ] Validation rejects a `repo_head`/`repo_base` artifact whose finding cites a file or line not present in the inspected workspace (not only inline anchors whose path is in the diff).
- [ ] Non-inline anchors (file-level, command-output, external-URL) are validated, not skipped — `validate_anchor` currently returns `Ok` for every non-`Inline` kind (`validation.rs:250-251`).
- [ ] Command-output / runtime citations must resolve to a captured transcript receipt; external-URL citations require policy research permission + an observation time.
- [ ] Adversarial fixtures: an artifact that hallucinates evidence beyond its tier FAILS `verify.sh` (today the "overstate" tests only mutate substituted JSON, never simulate a model citing unavailable content).
- [ ] The master prompt forces re-anchoring on changed hunks before emitting any finding, and may decline higher context tiers.

## Verification System
- Claim: every accepted finding is grounded in evidence actually available at the declared tier.
- Falsifier: a `repo_head:true` artifact whose finding cites an unread/nonexistent file passes validation clean (it does today — `validation.rs:128` is object-equality; `:249` checks only inline-path-in-diff).
- Driver: new adversarial fixtures through `verify.sh`; unit tests over `validate_*`.
- Grader: validation must FAIL each ungrounded fixture; commenting out the gate must break a test.
- Evidence packet: fixture set + expected `verify.sh` failures + a live re-run from ticket 006 showing real findings still pass.
- Cadence: every validation or prompt change.

## Children
1. Extend `validate_anchor` to cover non-inline kinds; verify file/line anchors against the inspected workspace when tier ≥ `repo_head`.
2. Add a Rust-side grounding gate that quarantines/rejects findings whose citation doesn't resolve to a real diff hunk, inspected line, or captured command output (model proposes, Rust verifies).
3. Adversarial fixtures for hallucinated-evidence-beyond-tier; wire into `verify.sh`.
4. Master-prompt: require re-anchoring on changed hunks before any finding; allow declining higher tiers.
5. (Schema ratification required — `ReviewArtifact.v1` is LOCKED) Add per-finding `confidence` + `severity` so callers filter signal/noise without Cerberus baking a fixed FP target.
6. Make the substrate config honor the request's `external_research` policy: `write_opencode_config` should deny `webfetch`/`websearch` when `policy.external_research == Forbid` (or the request should declare research allowed), so granted tools match the declared tier. **Dogfound 2026-06-22:** Cerberus's first self-review (PR #466) flagged this as a major finding in its own harness change — web tools were granted unconditionally while the request declared `external_research: forbid`.

## Notes
**Why:** lane-substrate F3 + lead vet — context-truth is enforced as object-equality (`validation.rs:128`), and `validate_anchor` (`:249-260`) checks only that an *inline* anchor's path is among changed files; non-inline anchors get no check at all. lane-exemplars #3 — the universal false-positive control across CodeRabbit/Qodo/Copilot is a separate verification pass that drops ungroundable findings; Cerberus half-specifies this ("every finding must cite a concrete anchor") but only in prose. lane-exemplars #1 — field evidence (SWE-PRBench, 2026) suggests *more flat context dilutes attention and lowers recall*, so the moat is enforced groundedness + attention-preserving context, not context volume — treat the specific benchmark as a hypothesis to confirm via 006's corpus, not settled fact. This is VISION's load-bearing Premise 2 and the real differentiation (lane-exemplars verdict: no competitor ships a portable, verdict-bearing artifact — the moat is the validation + context-truth invariants, not the JSON shape).
