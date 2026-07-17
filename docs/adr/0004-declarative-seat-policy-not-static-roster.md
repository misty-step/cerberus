# ADR 0004: Declarative Seat Policy, Not a Static Rust Roster

Date: 2026-07-17

Status: Accepted

## Context

`OPERATOR-CHARTER-2026-07-17.md` requires Phase 1 to "attack every PR with
focused frontier reviewer seats": on a meaningful diff, Cerberus must run a
mandatory floor of frontier-model reviewer seats, not just whatever the master
happens to choose. Powder card `cerberus-043` states this as: "Meaningful
diffs execute four schema-bound Tier 1 seats; deterministic Tier 0 executes
none; risk classifier adds required seats," and "Seat policy carries the
mandatory Factory model-vs-heuristic dimension while the master may add but
never subtract required lanes."

Three governing documents already lock a conflicting-looking rule:

- `AGENTS.md`: "The master reviewer may choose dynamic subagent lanes at
  runtime. Do not hardcode a static persona fleet into Rust."
- `VISION.md:21-28`: "One orchestrator master with dynamic substrate lanes —
  never a static roster... not in freezing yesterday's best reviewer personas
  (correctness/security/QA/...) into product code," and `VISION.md:88`: "No
  hardcoded reviewer personas in Rust. Reviewer topology is a runtime
  decision, never product architecture."
- `spec.md:21-26`: "Cerberus has no predefined correctness, security,
  architecture, QA, or research subagents. The master reviewer decides at
  runtime whether to launch substrate subagents, how many to launch, what
  perspectives matter... The Rust application validates capabilities and
  artifacts; it does not freeze reviewer topology into product architecture."

A charter that requires four mandatory seats and a spec that forbids a fixed
reviewer roster are not actually incompatible once the mechanism spec.md
already defines is taken seriously: `spec.md:224-228` states lane launch is
"a substrate interface over `ReviewerLanePlan` data, not a Rust enum of
reviewer personas," and the substrate already returns `ReviewerLaneReceipt.v1`
evidence per lane. `VISION.md:59-62` independently anticipates this shape:
"Named dimensions guide the master; they do not become hardcoded personas...
including the mandatory Factory dimension... Rust may require that this
dimension is present." VISION.md already accepts a Rust-enforced minimum
without accepting Rust-authored personas.

ADR 0003 names the applicable test directly: **"can a non-AI oracle decide
pass/fail with certainty?"** Whether a required *category* of seat ran, and
whether its receipt shows the *actual* provider/model family it claimed, is
exactly such an oracle question. What the seat's system prompt says, which
findings it raises, and how good those findings are is not — that stays model
judgment, governed by harness engineering and evals (ADR 0003 again), not by
a Rust `if` statement.

## Decision

Seat policy is trusted declarative data, interpreted by deterministic
admission code. It is never a Rust enum, match arm, or hardcoded prompt
string naming "SecurityReviewer," "CorrectnessReviewer," or similar personas.

1. **Tiering is deterministic and data-driven, not a model call.** A diff
   classifies as Tier 0 (no meaningful code change — e.g. pure
   docs/comments/whitespace by the same diff-shape logic already used
   elsewhere in the request builder) or Tier 1 (meaningful diff). This is an
   oracle question (ADR 0003): the diff either changes reviewable code or it
   does not.
2. **Tier 1 carries a policy-declared seat floor**, sourced from a trusted
   profile file (shape TBD in implementation, analogous to
   `config/omp-version.json`'s trusted-pin pattern), not from Rust source. The
   charter's current floor is four seats. The floor names *roles and
   required-dimension coverage* (including the mandatory Factory
   model-vs-heuristic dimension VISION.md already names), never fixed prompt
   text or a persona identifier baked into product code.
3. **The master still designs every lane.** Per `spec.md`'s existing
   `ReviewerLanePlan`/`ReviewerLaneReceipt.v1` contract, the master decides
   each lane's system prompt, scope, allowed context, model choice within
   policy, and stop condition at runtime from the actual diff. Rust never
   authors lane content.
4. **The master may add, never subtract.** Deterministic admission code
   checks the declared lane plan's role coverage against the policy floor
   *before* accepting the run: declared roles must be a superset of the
   policy-required roles. The master is free to add risk-triggered lanes
   Rust never anticipated; it cannot use judgment to drop a required one.
   Set-superset comparison is an oracle question, not a quality judgment.
5. **Receipts, not claims, prove the floor was met.** Deterministic code
   validates each seat's `ReviewerLaneReceipt.v1` against its *actual*
   observed provider/model identity (not the model's self-reported string),
   requires a two-family minimum across required seats, and treats timeout,
   malformed output, or every seat collapsing onto one family as
   `infrastructure_error` rather than a silently degraded pass. This mirrors
   the existing Phase 0 principle that a substrate's own claims are not
   trustworthy without an independent check (see `docs/omp-substrate.md`).
6. **Tier 0 stays free.** A deterministic no-meaningful-diff classification
   short-circuits before any seat spend, matching the charter's
   `local_runtime`/context-tier discipline already in the request builder.

None of this touches `ReviewRequest.v1` or `ReviewArtifact.v1`'s locked
shape; it is admission policy in front of the existing lane-receipt mechanism
`spec.md` already defines, so it does not itself require a `ReviewRequest.v1`/
`ReviewArtifact.v1` schema ADR. A schema change discovered during
implementation still needs its own ADR per `AGENTS.md`'s red line 4.

## Consequences

- Powder `cerberus-043`'s "meaningful diffs execute four schema-bound Tier 1
  seats; deterministic Tier 0 executes none; risk classifier adds required
  seats" criterion is implementable without violating `AGENTS.md` red line 1,
  `VISION.md:21-28/88`, or `spec.md:21-26/224-228` — those rules forbid Rust
  from authoring reviewer *content*, not from enforcing a *coverage floor*
  over data the master still writes.
- Seat policy data becomes a new trusted-input surface, alongside the
  existing OMP/OpenCode version pins. Its shape, storage, and update
  procedure are implementation decisions for the Phase 1 build, not this
  ADR; a materially different mechanism (e.g. moving it into
  `ReviewRequest.v1` itself) would need its own ADR.
- Any future contributor tempted to add `enum ReviewerRole { Security,
  Correctness, ... }` to Rust source is doing exactly what this ADR and its
  three parent documents forbid — that is a design-review rejection, not a
  missing unit test (per `AGENTS.md`'s framing of red line 1).
- **Named residual risk, not a settled non-issue:** a repo-committed,
  version-controlled policy file naming four required roles is a much softer
  form of the thing red line 1 forbids than a Rust enum is, but it is not
  zero distance from it. The distinction this ADR relies on is narrow and
  specific: the floor may name required *dimensions/roles* (what must be
  covered) and *count*, never a specific persona identity, system prompt, or
  fixed model. If a future seat-policy file starts encoding prompt text,
  persona names, or per-role model pins, that is no longer policy data — it
  is the forbidden roster wearing a YAML costume, and should be rejected in
  design review exactly as a Rust enum would be.

## Alternatives Considered

**Hardcode four hardcoded reviewer structs/prompts in Rust.**
Directly satisfies the charter's "four seats" language with the least code,
but is the literal violation `AGENTS.md`, `VISION.md`, and `spec.md` all
independently prohibit. Rejected.

**Let the master's own judgment decide seat count with no floor.**
Preserves "never a static roster" perfectly but drops the charter's actual
requirement — a diff-adaptive master could legitimately decide one seat
suffices, which is not "attacks every PR with focused frontier reviewer
seats." Rejected as under-delivering the charter.

**Encode the floor as a required field inside `ReviewRequest.v1`.**
Would make the floor caller-visible and auditable per-request, but widens the
locked schema for what is fundamentally server-side admission policy, and
would need its own schema ADR under red line 4 for no real benefit over a
trusted external policy file. Deferred; revisit if a caller genuinely needs
to override the floor per request.

## Revisit If

- The seat-policy data format proves too rigid for the risk classifier's
  needs and needs to grow into something closer to `ReviewRequest.v1` itself.
- A future evaluation shows the two-family-minimum identity check produces
  too many false `infrastructure_error`s against real provider behavior.
- The Factory model-vs-heuristic dimension needs enforcement beyond presence
  checking (e.g., scoring how well a lane actually applied it), which would
  cross back into the ADR 0003 "no oracle for faithfulness" boundary and
  belongs in evals, not this admission gate.
