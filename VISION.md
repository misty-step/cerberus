# Cerberus Vision

Status: canonical north star. Lifespan: long-lived product substrate — built to
outlive its current reviewer model, callers, and provider choices.

Cerberus is the self-contained, highly opinionated code-review organ for the
Misty Step Factory and its Weave loop. It turns an arbitrary change plus
whatever context is *safely* available into a trustworthy, replayable review
artifact — and, only when asked, projects that artifact into the operator's
normal review surface without ever overstating what it actually inspected.

Its current authority is advisory. Cerberus may inform humans, local agents,
CI hooks, and Bitterblossom-triggered PR runs, but it does not become a
repo-level merge gate until Crucible-measured consistency and false-confidence
floors justify that authority.

## The premise that makes this Cerberus

Two bets separate Cerberus from a generic "AI reviews your PR" tool:

1. **One orchestrator master with dynamic substrate lanes — never a static
   roster.** There is exactly one predefined agent, the Cerberus master. It
   understands the diff, names the review dimensions that matter, decides at
   runtime whether to launch focused subagent lanes, chooses cost/quality
   balance, and synthesizes one artifact. We invest in the general reviewing
   agent, its prompt, its context packaging, its reviewer-planning receipts, and
   its artifact grammar — not in freezing yesterday's best reviewer personas
   (correctness/security/QA/…) into product code.
2. **Context truth is an invariant, not a feature.** Every artifact records the
   exact context tier it could inspect (`diff_only` → `repo_head` →
   `repo_base_and_head` → `local_runtime` → `remote_runtime`), and validation
   *rejects* any finding that claims evidence beyond that tier. A confident,
   well-formed, wrong review is the failure this product exists to prevent.

## Who would miss it

Operators and calling agents who want a dependable review organ they can run
from any review context — a local branch, a GitHub PR, a task-system diff, a
hosted worker, a future event plane — and get back the *same* validated artifact
regardless of where the change came from. Misty Step's own repositories and
Factory loop are the first proof and the current ceiling; outside callers are
welcome only after the factory path is reliable, released, and measured.

## What must stay true

These are load-bearing. Implementation may change underneath them; these do not.

- **The stable seam is `ReviewRequest.v1 → ReviewArtifact.v1`.** Callers acquire
  context and map it in; renderers project the artifact out. The artifact is
  immutable and caller-neutral.
- **Rust owns the contract; the substrate owns judgment.** Rust owns contracts,
  capability boundaries, execution receipts, artifact validation, and rendering.
  The agent substrate (OpenCode default, OMP fallback, fixture for tests) owns
  reviewer reasoning and any runtime lane design. The line between what Rust may
  enforce (oracle-checkable contracts, safety, posting, citation resolution) and
  what only the model + evals may judge (faithfulness) is **ADR 0003**; review
  *quality* is earned by harness engineering and measured by evals, never by
  deterministic heuristics.
- **Named dimensions guide the master; they do not become hardcoded personas.**
  The master must consider product-relevant dimensions, including the mandatory
  Factory dimension: "heuristic where a model belongs, and model where
  deterministic code belongs." Rust may require that this dimension is present
  in prompt/receipt vocabulary; it must not pretend to score the judgment
  without Crucible evidence.
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
- **Advisory before blocking.** A FAIL verdict may be useful before it is
  authoritative. Blocking mode reopens only after pass^k consistency, key-recall,
  and false-confident finding rates clear a Crucible-owned threshold.

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
  workspaces is the runtime; containers and hosted workers are portability and
  hardening profiles *behind the same kernel contract*, not a pivot.
- **No direct provider API orchestration** unless a future ADR proves the
  substrate boundary genuinely cannot carry a needed capability.
- **Not a repo-level merge gate yet.** Cerberus stays advisory across local,
  CI, GitHub, and Bitterblossom-triggered runs until the measured consistency
  floor holds.

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
5. Code-review architecture should be optimized like an agent product, not
   frozen as folklore. Subagent topology, model choice, tool access, skill
   articulation, system prompt wording, and cost controls are all live variables
   to evaluate against real review outcomes.
6. The Factory's most important review dimension is model-boundary judgment:
   catch deterministic heuristics where a model is required, and catch model
   calls where deterministic code should own the behavior.

## What excellent looks like

- **Near term:** the documented path works. One command reviews a PR or local
  diff inside an isolated review workspace, produces a validated artifact,
  preserves receipts, and makes timeout, cost, duration, context used, and
  context skipped visible. Release automation cuts green releases, and GitHub
  projection has live create/update/idempotence proof.
- **Medium term:** Cerberus is the default advisory code-review organ for Misty
  Step repos. Local CLI, CI/pre-push, and Bitterblossom-triggered PR runs all
  use the same `ReviewRequest.v1 -> ReviewArtifact.v1` kernel. The master can
  compose dynamic reviewer lanes when the diff justifies them, and every stage
  leaves receipts that Crucible can score.
- **Blocking threshold:** trust is earned by a low rate of false-confident
  findings and a stable pass^k consistency floor measured against real artifacts.
  Until then, Cerberus comments and artifacts are advisory everywhere.
- **Long term:** the `ReviewArtifact.v1` contract is the durable asset — a
  substrate- and provider-neutral review primitive that other services build on,
  while the reviewer brain inside keeps improving without forcing callers or
  renderers to change.

## Where it sits

Cerberus is the **consolidation point for all code-review logic, structure, and
design** in its stack. In the Weave loop, Powder and GitHub expose work,
Bitterblossom triggers and executes reviewer workloads, Cerberus produces the
advisory review artifact, Crucible measures review quality, and consumers decide
where to publish the result. Cerberus owns the review organ, not the event plane,
work queue, release system, or eval lab.

Known consumers: **Bitterblossom** (defines its own review triggers and operating
substrate, then invokes Cerberus as the reviewer) and **Olympus**, which refactors
its Argus agent to invoke Cerberus rather than reimplement review. **Crucible**
and **Daedalus** evaluate Cerberus runs from emitted receipts. When a capability
could belong to Cerberus or to a consumer/adjacent system — a trigger, a queue, a
posting destination, an eval, a release workflow — it belongs to the consumer or
adjacent system unless an ADR argues otherwise. Cerberus stays a highly
opinionated, optimized review program, not a platform.

The locked MVP contract is `spec.md`. Architectural decisions live in
`docs/adr/`. This file decides direction; it should be revised when evidence
changes, not with every backlog edit.
