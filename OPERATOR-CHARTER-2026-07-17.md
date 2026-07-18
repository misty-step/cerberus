# Operator Charter — Cerberus Productization (2026-07-17)

You are the captain of this project. This charter is the operator's directive.
Reconcile it with VISION.md, spec.md, AGENTS.md, and the existing backlog; where
they conflict, this charter states current operator intent and you should
propose the reconciliation explicitly rather than silently picking one.

## Mission

Turn Cerberus into our own CodeRabbit/Greptile: a contained, highly opinionated,
locally-run code review application that attacks every PR with focused frontier
reviewer seats, synthesizes findings into durable review artifacts, publishes
them to GitHub as real PR reviews with inline comments, and gives the operator a
dashboard showing exactly what is running, against which PR, with what verdict.

Strategic context that motivates this:

- **Bitterblossom is backburnered.** No hosted event plane. Everything runs on
  this machine as a local control plane; only model inference is remote.
- **Reviews are where frontier intelligence goes.** Implementation can use
  commodity models; review seats get frontier models on subsidized subscription
  tokens (Anthropic, OpenAI Codex, xAI OAuth, ZAI, Kimi Code, Google
  Antigravity). **OpenRouter is denied by default** in every Cerberus model
  policy — explicit per-exception allowlist only. No surprise metered bills
  from loops.
- **OMP is the intended production substrate** — contingent on proving it runs
  headless, unsupervised, and reliable (Phase 0). Keep the existing
  `ReviewSubstrate` abstraction; do not rip out OpenCode. Flip the default when
  OMP earns it, keep OpenCode as fallback.
- Two prior ratified architecture documents exist as local artifacts. Read both:
  - `/Users/phaedrus/artifacts/public/a/omp-review-organ/index.html`
  - `/Users/phaedrus/artifacts/public/a/local-review-relay/index.html`

## Ratified architecture decisions (do not relitigate without evidence)

1. **Local control plane, cloud subscription inference.** No hosted workers, no
   self-hosted Actions runners in the review path, no webhook-first design.
2. **Outbound polling reconciler** (launchd-scheduled, single-shot, OS lock) is
   the primary PR discovery mechanism. Webhooks are optional wake-up hints
   added later, never correctness.
3. **Frontier review swarm never runs inline in pre-push.** Pre-push stays a
   sub-second receipt guard. An explicit `review-push`-style command exists for
   operators who want review-before-push.
4. **Merge authority is a dedicated least-privileged GitHub App Check Run**
   (versioned check name, strict/up-to-date or merge-queue semantics, no
   bypass). A user commit status is advisory only. The review process itself
   never holds the App credential; a trusted publisher consumes the validated
   artifact.
5. **Receipt identity** binds repo + PR + head SHA + base ref/SHA + evaluated
   test-merge/merge-group SHA + exact diff digest + review policy digest. Any
   change invalidates green.
6. **Review source is data, not executable configuration.** The reviewer runs
   from a trusted controller cwd, never executes checkout-owned code, with
   project extensions/skills/rules disabled and pinned reviewer profiles.
   A worktree is not a sandbox: v1 reviews operator/first-party branches only;
   fork/untrusted PRs are rejected until an OS/VM sandbox exists.
7. **Seat validation is deterministic**: schema-bound artifacts per seat,
   actual provider/model identity checked against the required seat, at least
   two model families independent, malformed/timeout/fallback-collapse =
   `infrastructure_error`, never PASS.
8. **Global provider semaphore**: one review workflow at a time, bounded child
   seats, one transient retry, no cross-family fallback that collapses seat
   independence.
9. **Remote side effects** go through transactional intent (outbox) with stable
   operation IDs and readback before completion. Update-by-ID, never blind
   create.

## Review doctrine (the opinionated core)

Mandatory Tier 1 seats for any meaningful diff:

| Seat | Question |
|---|---|
| Correctness | Does the change satisfy its observable contract through the real entrypoint? |
| Thermonuclear maintainability | What structural regression or wrong abstraction is being introduced? |
| Erasure/simplicity | What should be deleted, collapsed, or replaced with an existing primitive? |
| Premise/idiot-check | Is this the right change at all? |

Risk-triggered seats: security, performance, product/UX, operations,
contract/evolution. Deterministic classification decides tiers; Tier 0
(mechanical/doc-only) gets no model seats. CI/QA results are inputs the
review must consider; Cerberus does not replace repo CI.

## Deliverables (phased; each phase has a proof gate)

**Phase 0 — OMP headless reliability.** The installed `omp` v17.0.2 hit a
`pi_natives` sentinel mismatch during headless probing. Repair, then prove: a
subscription-backed single-shot `--mode json` session completes cleanly with a
parseable lifecycle, repeatedly, unsupervised. This gates the OMP-substrate
decision.

**Phase 1 — hardened local review runner.** One fresh headless substrate
process per review, four schema-bound frontier seats, model-identity
validation, digest-bound receipt persisted locally. Same input reuses the
receipt; any input/policy/model change invalidates it. Much of ReviewKernel
already does this — gap-analyze before building.

**Phase 2 — dashboard + artifact store.** Local web dashboard (this is an
explicit operator requirement, not polish): live runs and seat status, PR
queue, verdicts, findings, costs/latency, artifact browser, run history.
SQLite + filesystem store. It must look good — use the Misty Step Aesthetic
system. Also feed milestone events to the Overmind operator feed.

**Phase 3 — GitHub reconciler + publication.** launchd-scheduled outbound
polling over a registered repo set; publication as real GitHub PR reviews with
inline comments (schema already supports findings with locations) plus the
dedicated GitHub App Check Run for enforcement. Advisory mode first, then
branch protection.

**Phase 4 — remediation loop.** PR opened → Cerberus attacks → a responder
agent (commodity model) takes the review artifact + CI/QA state, iterates the
PR, pushes fixes → re-review on new head. Bounded attempts (default 3), then
escalate to the operator via dashboard + Overmind. Clean loop end = auto-merge
**only for repos explicitly opted in**, only via the App check, never
auto-deploy.

**Phase 5 — containerization + auth profiles.** Runs local-first with
subscription auth (mounted auth state); API-key profile for cloud/remote where
subscription auth is not viable. One image, two auth profiles.

**Phase 6 — fleet work loop (separate program, shared primitives).** Per-repo
orchestrator that pulls ready cards from Powder, routes by capability hints in
the card, dispatches commodity implementation agents, opens PRs, and hands off
to Cerberus. Design doc first; do not couple it to the review product's
critical path.

## Harness/workflow integration (coordinate, don't own)

- Doctrine change for the fleet: **agents open PRs; agents do not merge or
  deploy.** Merging belongs to the Cerberus loop (or the operator). Propose the
  exact edits to the Roster/omp-config doctrine as a PR for operator approval.
- Powder is the work ledger. The `cerberus` repo exists in Powder with prior
  cards — read them, close/supersede stale ones, and file this charter's
  phases as cards with acceptance criteria before implementing.
- Misty Step repos use `master`. Repo gate: `./scripts/verify.sh`.

## Non-goals (v1)

Fork/untrusted PR review; Canary incident triage (separate reconciler later —
share only the hardened runner/semaphore libraries); resident daemons where
launchd suffices; Bitterblossom deployment; auto-deploy; replacing repo CI.

## Operating expectations for you, the captain

- Read VISION.md, spec.md, AGENTS.md, docs/, the two artifact reports, and the
  Powder board before writing code. Produce a reconciled plan: what exists,
  what changes, what's new, phase by phase, with proof gates.
- Dispatch focused subagents for implementation lanes; you own synthesis,
  integration, and the acceptance boundary. Implementation lanes use commodity
  models; reserve frontier effort for design review and judgment.
- Open PRs against master with evidence; do not merge them yourself.
- Keep Powder cards and the Overmind feed current at milestones.
- Escalate to the operator when: a phase gate fails, a security boundary is
  implicated, spend policy is ambiguous, or a decision materially narrows the
  product.
