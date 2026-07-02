# Evolve Cerberus into an orchestrator master agent

Priority: P1 | Status: active — machinery built, not wired to a live caller (see 2026-07-02 verification note) | Estimate: L | Factory epic: 3

## Goal

Move Cerberus from a single-model review harness toward the Factory direction:
one strong master reviewer that understands an arbitrary diff, composes a
bespoke cost/quality-balanced team of reviewer subagents when useful, and
synthesizes those lanes into one validated `ReviewArtifact.v1` that can be
pushed anywhere.

## Oracle

- [x] Every review run has an explicit diff-understanding stage that summarizes
      changed surfaces, risk shape, available context, and what was skipped.
      Holds: `build_reviewer_plan` runs unconditionally inside
      `ReviewKernel::review` (`kernel.rs:77`) on every real review.
- [ ] The master emits a reviewer-team plan when it chooses lanes: scope,
      allowed context tier, model/substrate choice, cost budget, stop condition,
      and expected output shape.
      **Does not hold end-to-end.** The plan schema/fields exist and are
      written every run, but nothing lets the master *model* actually choose
      lanes at runtime: `build_master_prompt` never instructs the model on how
      to launch a lane (its only lane-related line is passive — "if lane
      evidence is attached, use it as evidence"), `mcp.rs` exposes no
      lane-launch tool, and `launch_planned_child_lanes`/
      `ReviewerLaneSubstrate` have zero callers outside their own unit tests.
      `lane_decision` is always `single_master` in practice today.
- [ ] Lane evidence is captured as receipts and synthesized into a single
      validated `ReviewArtifact.v1`; child-lane claims cannot bypass artifact
      validation.
      **Proven only in unit tests, not live.** `synthesize_lane_receipts_into_artifact`
      doesn't itself call `validate_artifact_for_request`; tests call validation
      afterward on the same object, proving no bypass *in test*. Since the
      function has no live caller (same gap as above), this has never run
      through the real `harness.rs`/`main.rs` validation call sites end-to-end.
- [x] A cheap review still runs as a single master when the diff does not justify
      lanes. Dynamic composition must reduce to the simple path.
      Holds: `verify.sh` asserts `lane_decision.mode == "single_master"` and
      zero child lanes on the fixture path.
- [ ] `./scripts/verify.sh` covers the fixture path for no-lane and with-lane
      runs; one live local diff run leaves a receipt packet proving the stage
      boundaries.
      **Does not hold.** `verify.sh` only exercises the no-lane fixture path —
      no with-lane (or fabricated-lane-receipt) case, and no live model call
      anywhere in the gate (every `--harness opencode` invocation pins the fake
      binary), so no live receipt packet demonstrating the stage boundaries
      exists today.

## Children

1. **Done:** introduce a reviewer-plan receipt: diff understanding, lane
   decision, budget, and synthesis notes. PR #490 added
   `cerberus.reviewer_plan.v1`, writes it beside `review`, persisted
   `review-diff`, and `review-pr` artifacts, links it from
   `ReviewReceiptBundle.v1`, and pins the no-lane single-master path in
   `./scripts/verify.sh`.
2. **Done:** add a substrate interface for launching scoped reviewer lanes
   without encoding static personas in Rust. PR #491 added
   `ReviewerLaneSubstrate`, `ReviewerLaneLaunch`,
   `launch_planned_child_lanes`, and `ReviewerLaneReceipt.v1`; the unit test
   launches an arbitrary `model-boundary-risk` role from plan data.
3. **Done:** add synthesis prompt/schema instructions that merge lane evidence
   into one artifact while preserving context-tier truth and citation
   requirements. PR #492 teaches both prompt surfaces that
   `ReviewerLaneReceipt.v1` is evidence, must flow through artifact
   `receipts[]`, and cannot raise context capabilities or bypass anchor,
   citation, and validation rules.
4. **Done:** add fixture coverage for no-lane, one-lane, and
   failed-lane-degraded synthesis paths. The fixtures pin empty lane evidence as
   a no-op, arbitrary completed lane roles as generic reviewer receipts with the
   dynamic role preserved as `perspective`, and failed lanes as degraded
   artifacts with copied lane errors and residual risk.
5. **Not started — the actual "master chooses lanes at runtime" wiring.**
   Children 1-4 built the plan/launch/synthesis *machinery* and pinned it with
   unit + fixture tests, but nothing on the model-facing surface can trigger
   it: no prompt instruction tells the master how to request a lane, no MCP
   tool exposes lane-launching, and `launch_planned_child_lanes`/
   `synthesize_lane_receipts_into_artifact` have zero callers outside their
   own tests. This is a real design decision (does the model request a lane
   via a new MCP tool call? via a structured field in its own output that
   Rust then acts on and re-invokes the model? something else?) — not a
   quick mechanical follow-up, which is why it's left for explicit scoping
   rather than picked up opportunistically. Also needs a with-lane (or
   fabricated-lane-receipt) case in `verify.sh` and one live receipt packet
   from a real diff run once the wiring exists.

## Notes

This epic is intentionally downstream of `022` and `023`. The orchestration
surface should not land before the documented single-master path and the
dimension vocabulary are stable enough to measure.

**2026-07-02 verification note (overnight backlog-hygiene pass):** children
1-4's PRs (#490-492) are real and correctly described, but the ticket's own
oracle was re-checked against live code (not just "children marked Done") and
3 of 5 bullets don't hold end-to-end — see the inline oracle notes above.
Verdict: **do not move to `_done/`**. The plan/receipt/synthesis *scaffolding*
is solid and well-tested; the "master reviewer dynamically composes a team"
behavior the epic's Goal describes does not exist yet from the model's
perspective. Added child 5 to name the gap explicitly.
