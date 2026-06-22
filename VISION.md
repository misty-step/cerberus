# Cerberus Vision

Status: canonical north star. Lifespan: long-lived product substrate — built to
outlive its current reviewer model, callers, and provider choices.

Cerberus turns an arbitrary change plus whatever context is *safely* available
into a trustworthy, replayable review artifact — and, only when asked, projects
that artifact into the operator's normal review surface without ever overstating
what it actually inspected.

## The premise that makes this Cerberus

Two bets separate Cerberus from a generic "AI reviews your PR" tool:

1. **One master reviewer with dynamic substrate lanes — never a static roster.**
   There is exactly one predefined agent, the Cerberus master. It decides at
   runtime whether to launch focused subagent lanes, how many, and with what
   scope. We invest in the general reviewing agent, its prompt, its context
   packaging, and its artifact grammar — not in freezing yesterday's best
   reviewer personas (correctness/security/QA/…) into product code.
2. **Context truth is an invariant, not a feature.** Every artifact records the
   exact context tier it could inspect (`diff_only` → `repo_head` →
   `repo_base_and_head` → `local_runtime` → `remote_runtime`), and validation
   *rejects* any finding that claims evidence beyond that tier. A confident,
   well-formed, wrong review is the failure this product exists to prevent.

## Who would miss it

Operators who want a dependable review agent they can run from any review
context — a local branch, a GitHub PR, a task-system diff, a hosted worker, a
future event plane — and get back the *same* validated artifact regardless of
where the change came from. Misty Step's own repositories are the first proof,
not the ceiling: the request/artifact contract is built so outside callers and
future services can adopt it without inheriting our GitHub conventions or our
substrate choice.

## What must stay true

These are load-bearing. Implementation may change underneath them; these do not.

- **The stable seam is `ReviewRequest.v1 → ReviewArtifact.v1`.** Callers acquire
  context and map it in; renderers project the artifact out. The artifact is
  immutable and caller-neutral.
- **Rust owns the contract; the substrate owns judgment.** Rust owns contracts,
  capability boundaries, execution receipts, artifact validation, and rendering.
  The agent substrate (OpenCode default, OMP fallback, fixture for tests) owns
  reviewer reasoning and any runtime lane design.
- **Evidence discipline.** Every finding cites a concrete anchor: a diff hunk,
  an inspected file, command/test/log output, or an external URL with an
  observation time. Model memory alone is never evidence.
- **Safety posture is non-negotiable.** No ambient credential inheritance, no
  prompt/diff in argv, substrate binaries resolved only from trusted absolute
  paths, bounded time/output, no orphaned children, exactly one validated
  artifact candidate per run.
- **Verification gates publication.** The loop (`./scripts/verify.sh`) must catch
  likely publication and execution failures *before* Cerberus is trusted as an
  automatic reviewer — not after.

## What this repo refuses

Drift here is how narrow tools become unmaintainable platforms. The scope stays
narrow on purpose.

- **Not an evaluation lab.** Cerberus emits redacted, replayable
  `ReviewReceiptBundle.v1` receipts so upstream labs (Daedalus) can score real
  runs. It does not own leaderboards, harness-vs-harness matrices, reviewer-config
  promotion, eval dashboards, or long-lived benchmark storage.
- **No hardcoded reviewer personas in Rust.** Reviewer topology is a runtime
  decision, never product architecture.
- **No GitHub-only boundary.** GitHub is one projection adapter among many, never
  the core execution path.
- **Not a hosted multi-tenant service.** Local process execution plus ephemeral
  workspaces is the runtime; containers and hosted workers are later hardening
  profiles *behind the same kernel contract*, not a pivot.
- **No direct provider API orchestration** unless a future ADR proves the
  substrate boundary genuinely cannot carry a needed capability.

## Strategic bets

These are why the chosen shape should age better than the obvious alternatives.

1. A strict, validated review **artifact** is worth more than a clever reviewer
   transcript.
2. A single excellent master reviewer with dynamic lanes beats a static reviewer
   roster embedded in product code.
3. A caller-neutral artifact plus small projection adapters ages better than a
   GitHub-native core.
4. Keeping the execution kernel substrate- and provider-neutral lets upstream
   labs evaluate models and harnesses while Cerberus stays the runner and
   contract. The reviewer model can be replaced wholesale without breaking
   callers.

## What excellent looks like

- **Near term:** Cerberus is the default code review agent for Misty Step repos.
  One command reviews a PR inside an isolated review workspace, produces a
  validated artifact, publishes idempotent GitHub checks/reviews/comments, and
  preserves receipts. Operators can see what context was used, what was skipped,
  what time/cost it took, and why each comment exists.
- **Medium term:** outside callers and task systems map their own sources into
  `ReviewRequest.v1` without touching Cerberus internals; the substrate is
  swappable per run; trust is earned by a low rate of false-confident findings,
  measured against upstream evaluation of real artifacts.
- **Long term:** the `ReviewArtifact.v1` contract is the durable asset — a
  substrate- and provider-neutral review primitive that other services build on,
  while the reviewer brain inside keeps improving without forcing callers or
  renderers to change.

## Where it sits

Cerberus is the **consolidation point for all code-review logic, structure, and
design** in its stack. Consumers pull Cerberus and run it as their reviewer; they
own what *triggers* a review, what *substrate* it runs on, and *where* results are
posted — Cerberus is deliberately agnostic to all three. Known consumers:
**Bitterblossom** (defines its own review triggers and operating substrate, then
invokes Cerberus as the reviewer) and **Olympus**, which refactors its Argus agent
to invoke Cerberus rather than reimplement review. **Daedalus** evaluates Cerberus
runs from emitted receipts. When a capability could belong to Cerberus or to a
consumer/adjacent system — a trigger, a queue, a posting destination, an eval — it
belongs to the consumer unless an ADR argues otherwise. Cerberus stays a highly
opinionated, optimized review program, not a platform.

The locked MVP contract is `spec.md`. Architectural decisions live in
`docs/adr/`. This file decides direction; it should be revised when evidence
changes, not with every backlog edit.
