# Evolve Cerberus into an orchestrator master agent

Priority: P1 | Status: ready | Estimate: L | Factory epic: 3

## Goal

Move Cerberus from a single-model review harness toward the Factory direction:
one strong master reviewer that understands an arbitrary diff, composes a
bespoke cost/quality-balanced team of reviewer subagents when useful, and
synthesizes those lanes into one validated `ReviewArtifact.v1` that can be
pushed anywhere.

## Oracle

- [ ] Every review run has an explicit diff-understanding stage that summarizes
      changed surfaces, risk shape, available context, and what was skipped.
- [ ] The master emits a reviewer-team plan when it chooses lanes: scope,
      allowed context tier, model/substrate choice, cost budget, stop condition,
      and expected output shape.
- [ ] Lane evidence is captured as receipts and synthesized into a single
      validated `ReviewArtifact.v1`; child-lane claims cannot bypass artifact
      validation.
- [ ] A cheap review still runs as a single master when the diff does not justify
      lanes. Dynamic composition must reduce to the simple path.
- [ ] `./scripts/verify.sh` covers the fixture path for no-lane and with-lane
      runs; one live local diff run leaves a receipt packet proving the stage
      boundaries.

## Children

1. Introduce a reviewer-plan receipt: diff understanding, lane decision, budget,
   and synthesis notes.
2. Add a substrate interface for launching scoped reviewer lanes without
   encoding static personas in Rust.
3. Add synthesis prompt/schema instructions that merge lane evidence into one
   artifact while preserving context-tier truth and citation requirements.
4. Add fixture coverage for no-lane, one-lane, and failed-lane-degraded paths.

## Notes

This epic is intentionally downstream of `022` and `023`. The orchestration
surface should not land before the documented single-master path and the
dimension vocabulary are stable enough to measure.
