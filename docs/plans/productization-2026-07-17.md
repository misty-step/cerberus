# Cerberus productization plan — 2026-07-17

## Authority and mission

This plan reconciles, in order:

1. `OPERATOR-CHARTER-2026-07-17.md` — current operator intent.
2. `VISION.md` — the caller-neutral review-kernel north star.
3. `spec.md` — the locked MVP request/artifact/kernel contract.
4. `AGENTS.md` — repository safety and delivery rules.
5. `docs/adr/` — ratified implementation decisions.
6. The Review Organ and Local Review Relay architecture reports:
   - `/Users/phaedrus/artifacts/public/a/omp-review-organ/index.html`
   - `/Users/phaedrus/artifacts/public/a/local-review-relay/index.html`
7. Powder cards in the `cerberus` repository.

Mission: turn Cerberus into a local CodeRabbit/Greptile-style application. A local controller discovers eligible first-party PRs, attacks each meaningful diff with independent subscription-backed frontier review seats, synthesizes a validated `ReviewArtifact.v1`, persists and displays the run, and publishes transactional GitHub reviews and checks. Cerberus never replaces repository CI. Agents open PRs; they do not merge or deploy.

## Reconciled decisions

The charter supersedes earlier deployment assumptions but does not silently rewrite locked contracts.

| Tension | Reconciliation | Required record |
|---|---|---|
| `AGENTS.md` forbids a static reviewer roster in Rust; the charter requires four Tier 1 seats. | Mandatory seats are trusted declarative policy/profile data interpreted by deterministic admission code, not Rust persona enums or hard-coded prompts. The master may add risk-triggered lanes, but cannot remove required seats. | Phase 1 ADR, matching `spec.md` Core Product Rule and `VISION.md` premise revisions, and fresh-context design review. |
| ADR 0002 and `spec.md` make OpenCode the default; the charter intends OMP. | Phase 0 proves OMP lifecycle and validated artifact emission first. A later superseding ADR may flip the default. OpenCode remains a tested fallback behind `ReviewSubstrate`, but must itself satisfy subscription-first policy or carry a digested explicit exception. | Phase 0 evidence, fallback-viability proof, then ADR in Phase 1. |
| `VISION.md` and `spec.md` describe a caller-neutral kernel; the charter requires a dashboard and reconciler in this product. | Keep `ReviewKernel` and schemas caller-neutral. Add an in-repo local-control-plane consumer around the kernel, storage, and publication adapters. | Phase 2 boundary ADR. |
| The Review Organ assigned durable workflow state to Bitterblossom. The later Local Review Relay and charter remove the hosted event plane. | Local SQLite/filesystem state plus launchd single-shot reconciliation own this product's control plane. Webhooks are optional wake-up hints only. | Phase 2/3 boundary ADRs. |
| Existing OpenRouter-first/scoped-key paths conflict with subscription-first spend policy. | Retain useful containment code, but trusted model policy denies OpenRouter by default. Any OpenRouter use needs an explicit reviewed per-exception allowlist. | Phase 1 model-policy contract. |
| Existing container work describes untrusted-PR capability; the charter excludes fork/untrusted PRs from v1. | Skip fork/untrusted PRs. Existing containment remains reusable research, not a v1 trust claim. Re-entry requires an OS/VM sandbox and operator approval. | `cerberus-013` superseded. |
| Existing GitHub posting can create comments/checks, but the charter reserves merge authority for a dedicated App publisher. | Treat current user-token publication as advisory. The review process emits a validated artifact; a separate least-privileged publisher owns the App credential and readback. | Phase 3 security review. |
| Existing quality cards do not yet justify blocking merges. | Advisory publication may ship first. Branch protection and opt-in auto-merge remain disabled until `cerberus-026` establishes the consistency floor. | Linked Phase 3/4 gate. |

## Existing foundation and product gaps

### Reuse without rebuilding

- `ReviewRequest.v1` and `ReviewArtifact.v1`, committed JSON schema, canonical fixture, validation, rendering, and verdict-gated exits.
- `ReviewKernel` / `ReviewSubstrate` seam with fixture, OpenCode, OMP, and container-OpenCode implementations.
- Private prompt/request files, `env_clear()`, explicit environment allowlist, trusted binary resolution, bounded execution, process-group timeout handling, and isolated workspaces.
- Request construction from local diff and one GitHub PR, runtime context tiers, exact request digest, receipt bundles, reviewer-plan receipts, telemetry, and durable artifact files.
- Dormant generic reviewer-lane launch/receipt/synthesis machinery, which can be activated without inventing another artifact shape.
- Real GitHub PR review projection, inline comments, check-run posting, explicit token sources, and read-side PR acquisition.
- Container and scoped-key hardening primitives, retained for future sandbox work but not used to admit untrusted v1 sources.
- Crucible-compatible evaluation receipts and existing doctrine/evaluation cards.

### Missing or incomplete

- The four mandatory seats do not execute end to end; current live behavior is one master.
- Actual provider/model/family identity and two-family independence are not admitted per seat.
- No trusted subscription-first model policy; OpenRouter is still default-shaped in older paths.
- No cross-process global provider semaphore or constrained retry policy.
- Receipts are persisted but not reused as an identity-bound cache.
- Receipt identity lacks the complete PR/base/test-merge/policy tuple required for merge authority.
- No SQLite run index, filesystem artifact catalog, dashboard, queue, live seat status, or Overmind product events.
- No registered-repository poller, launchd job, OS lock, transactional outbox, or remote readback reconciler.
- Existing GitHub publication is not separated behind a dedicated App authority.
- No bounded responder state machine, operator escalation, or opt-in App-gated merge path.
- No one-image/two-auth-profile packaging.
- No separate Powder-to-implementation fleet-loop design.

## Delivery rules common to every phase

- One phase gate failing pauses the dependent phase. Record the exact falsifier and escalate instead of narrowing the product.
- Security-boundary, spend-policy, or product-scope decisions require operator escalation.
- Every behavioral PR targets `master`, contains its live proof, passes `./scripts/verify.sh`, and receives fresh-context review. Never merge or deploy.
- The canonical artifact is `ReviewArtifact.v1`; projections may not become a second source of truth.
- Missing/malformed/stale/timeout/fallback-collapsed review evidence cannot yield PASS.
- Remote side effects use transactional intent, stable operation IDs, update-by-ID, and readback before local completion.
- Review source is data: trusted controller cwd, project extensions/skills/rules disabled, no checkout-owned execution, first-party branches only.
- Hooks stay deterministic and fast. Frontier review is asynchronous or explicit, never inline in universal pre-push.

## Phase 0 — OMP headless reliability

**Powder:** `cerberus-042`  
**Purpose:** decide whether OMP has earned production-substrate status. Do not flip defaults here.

### Current state

- Canonical active executable: `~/.bun/bin/omp`, package version 17.0.2 with matching `@oh-my-pi/pi-natives` packages.
- Quarantined standalone: `~/.local/bin/omp.broken-standalone-17.0.2`.
- The versioned standalone native cache and npm leaf addon are byte/size-distinct despite the same declared version, consistent with the charter's historical skew.
- A `--version` probe succeeds but does not load `pi_natives`; it cannot falsify the sentinel failure.
- Cerberus currently runs OMP headlessly but omits `--mode json`.
- Cerberus intentionally clears HOME/XDG state. Subscription auth therefore must be made available explicitly, not recovered through ambient home inheritance.

### Change

1. Add `--mode json` to the OMP `ReviewSubstrate` command and pin the argument contract with a unit test.
2. Pin or record the exact OMP executable/version using the existing trusted-binary pattern; do not trust arbitrary `$PATH` precedence.
3. Probe a real pi_natives-dependent tool path. Only repair/delete the versioned cache if this live probe reproduces the mismatch; otherwise record the failure as historical and avoid destructive folklore.
4. Run direct subscription-backed single-shot prompts with fresh sessions and parse every NDJSON lifecycle.
5. Run the exact Cerberus-shaped path: trusted cwd, private `@prompt` file, null stdin, fresh HOME/XDG, disabled extensions/skills/rules/PTY/session, and explicit subscription-auth access.
6. Retain a redacted evidence packet with executable digest/version, command shape, lifecycle counts, terminal event, exit status, and one Cerberus-produced artifact-validation result.

### Proof gate

GO only when:

- a real tool-using prompt reaches a successful terminal lifecycle;
- five direct and five Cerberus-shaped fresh runs complete unsupervised;
- every stdout stream is parseable NDJSON with the expected terminal lifecycle;
- at least one exact Cerberus entrypoint run emits a `ReviewArtifact.v1` that passes request-bound validation;
- no sentinel mismatch, interactive prompt, hidden fallback, or leaked private path/credential appears;
- the Phase 0 PR passes `./scripts/verify.sh` and independent live verification.

NO-GO: attach the failing transcript to `cerberus-042` and escalate the failed phase gate. Retaining OpenCode as default is permitted only after Phase 1 policy proves a subscription-backed OpenCode path or admits a reviewed, digested OpenRouter exception.

## Phase 1 — hardened local multi-seat runner

**Powder:** `cerberus-043`  
**Blocked by:** Phase 0.  
**Related:** `cerberus-020`, `cerberus-026`; supersedes unfinished `cerberus-024` behavior.

### Reuse

`ReviewKernel`, request/artifact validation, execution hardening, receipt bundles, telemetry, generic lane receipts/synthesis, and OpenCode/OMP substrate abstraction.

### Change

- Deterministically classify Tier 0/1/2 from the frozen diff and policy.
- Load the four Tier 1 seats from trusted declarative policy/profile data. Let the master add, never subtract, risk-triggered lanes.
- Carry the mandatory Factory dimension — heuristic where a model belongs, and model where deterministic code belongs — in trusted seat/prompt and receipt vocabulary.
- Require schema-valid per-seat artifacts and validate actual provider/model/family against the admitted seat.
- Require at least two model families; forbid fallback that collapses independence.
- Add one global workflow semaphore, bounded child concurrency, and one transient retry.
- Add subscription-first provider policy with OpenRouter denied unless an explicit exception is admitted and digested.
- Prove the OpenCode fallback under that policy: subscription-backed live smoke preferred; otherwise one reviewed, digested OpenRouter exception scoped to the fallback lane.
- Extend receipt identity to repo + PR + head + base ref/SHA + evaluated merge/merge-group SHA + exact diff + review policy + seat/model profile.
- Reuse an identical receipt; invalidate on any bound input change.
- After Phase 0 artifact proof, matching ADR/`spec.md`/`VISION.md` revisions, and fallback-viability proof, consider OMP default; keep OpenCode live-smoked as fallback.

### Proof gate

A meaningful first-party diff yields four independent seat artifacts and one aggregate. Tier 0 yields no model calls. Identity mismatch, malformed seat, timeout, missing family, fallback collapse, or any receipt-input mutation yields `infrastructure_error`/stale and never PASS. An identical request is a measured cache hit. Live review and `./scripts/verify.sh` pass.

## Phase 2 — dashboard and durable artifact store

**Powder:** `cerberus-044`  
**Blocked by:** Phase 1.  
**Related:** `cerberus-019`, `cerberus-028`, `cerberus-030`.

### Reuse

Persisted artifact/receipt files, telemetry, rendered review markdown, CLI entrypoints, and Misty Step Aesthetic assets/patterns from existing cards.

### Change

- Add SQLite for registered repositories, PR queue, run/seat lifecycle, receipt identity, outbox intent, and history indexes.
- Keep complete artifacts/transcripts in a filesystem store addressed by stable run/artifact identity; SQLite stores metadata and pointers.
- Add a local web dashboard for queue, active runs, seat status, verdicts, findings, latency/cost, artifact browsing, and history.
- Emit sparse milestone events to Overmind with stable run/artifact references.
- Apply Misty Step Aesthetic and accessibility requirements.

### Proof gate

Browser-drive a queued review through live seats to a visible artifact. Restart the process and prove the run/history/artifact catalog reconciles without loss. Verify desktop and narrow layouts, keyboard/focus behavior, empty/failure/stale states, and Overmind milestone readback. `./scripts/verify.sh` passes.

## Phase 3 — GitHub reconciler and transactional publication

**Powder:** `cerberus-045`  
**Blocked by:** Phase 2.  
**Enforcement additionally gated by:** `cerberus-026`.

### Reuse

Single-PR acquisition, inline-comment projection, check-run payloads, explicit GitHub token sources, artifact locations, and validation.

### Change

- Poll a registered active-repository set from a launchd-scheduled single-shot command.
- Hold an OS lock, paginate/batch responsibly, coalesce stale heads, and recover after sleep/offline/restart.
- Reject drafts and fork/untrusted PRs.
- Read current repository CI/check and QA receipts as review inputs without executing checkout-owned code.
- Persist publication intent transactionally. Publish/update by stable operation ID and read back before completion.
- Publish real GitHub PR reviews with inline comments.
- Isolate a dedicated least-privileged GitHub App Check Run publisher from review execution credentials.
- Roll out advisory first. Enable required checks only after the quality floor and operator-approved branch-protection change.
- Deliver a sub-second exact-HEAD receipt guard for pre-push and an explicit `review-push` command that runs/resumes review before pushing; neither becomes merge authority.

### Proof gate

Repeated polling and crash replay converge on one current-input review, one PR review projection, and one versioned Check Run without duplicate comments/checks or stale green. A user status cannot impersonate the required App check. Head/base/policy/merge-group mutations invalidate green. The pre-push guard validates an exact-current receipt within one second and never launches a model; `review-push` blocks its own explicit workflow until a fresh green receipt, then pushes. Live first-party PR proof and `./scripts/verify.sh` pass.

## Phase 4 — bounded remediation loop

**Powder:** `cerberus-046`  
**Blocked by:** Phase 3 and `cerberus-026`.

### Change

- Ratify the responder security boundary before implementation: branch-write credential, executable checkout scope, and separation from reviewer subscription auth and App publication authority.
- Hand the immutable exact-head review artifact plus CI/QA state to a commodity responder.
- Push fixes to the PR branch, then force a new-head re-review; never carry green forward.
- Bound attempts to three by default. On exhaustion or ambiguous repair, escalate in dashboard and Overmind.
- Permit auto-merge only for explicitly opted-in repositories, only through the dedicated App check under strict up-to-date/merge-queue semantics, with no bypass.
- Never auto-deploy.

### Proof gate

One first-party sandbox PR demonstrates artifact → fix → pushed head → full re-review. A second scenario exhausts the bound and produces one operator escalation. Stale inputs, CI regression, failed push, and credential separation are exercised. Non-opted repositories stop at operator-ready green.

## Phase 5 — one image, two auth profiles

**Powder:** `cerberus-047`  
**Blocked by:** Phase 4.  
**Related:** `cerberus-027`.

### Change

- Build one immutable image for the local control plane.
- Subscription profile mounts supported provider auth state; API-key profile accepts explicit runtime injection for remote/cloud contexts.
- Preserve env allowlists, trusted binaries, provider policy, and seat identity checks.
- Keep prompts, diffs, credentials, and raw tokens out of argv, layers, manifests, logs, and artifacts.

### Proof gate

Build once and complete the same review through both profiles. Inspect image history, process args, mounts, and output for secret-boundary violations. Both receipts identify the expected provider/model/family and `./scripts/verify.sh` passes.

## Phase 6 — separate fleet work loop

**Powder:** `cerberus-048`  
**Program relationship:** shared primitives, not Cerberus critical-path ownership.

### Change

Design before code: a per-repository orchestrator claims ready Powder cards, routes by card capability hints, dispatches commodity implementation agents, opens PRs, and hands them to Cerberus. Specify claim/lease semantics, trust and credential boundaries, failure recovery, PR ownership, and review handoff. Propose the fleet doctrine change — agents open PRs; agents do not merge or deploy — as a separate Roster/omp-config PR for operator approval.

### Proof gate

An approved ADR/design survives adversarial architecture review and defines an executable tracer bullet from Powder card to implementation PR to Cerberus handoff. No runtime implementation lands before approval. Cerberus remains caller-neutral.

## Powder reconciliation

- Epic: `cerberus-041`.
- Phase cards: `cerberus-042` through `cerberus-048`, each with acceptance criteria and proof plan.
- Superseded:
  - `cerberus-013` — untrusted PR work is outside v1; delivered containment remains reusable.
  - `cerberus-024` — remaining orchestration work is replaced by Phase 1's deterministic mandatory-seat policy plus dynamic risk lanes.
  - `cerberus-025` — Bitterblossom/pre-push deployment trio is replaced by the local polling reconciler and fast receipt guard.
- Retained and linked:
  - `cerberus-019`, `cerberus-028`, `cerberus-030` — dashboard aesthetic/artifact presentation.
  - `cerberus-020` — doctrine measurement.
  - `cerberus-026` — quality floor before blocking enforcement or auto-merge.
  - `cerberus-027` — external/API-key auth documentation.
  - `cerberus-029` — historical live-substrate smoke evidence.

## PR sequence

1. Phase 0: OMP JSON-mode invocation, repeated lifecycle proof, and one request-validated Cerberus artifact; no default change.
2. Phase 1 ADR(s): mandatory declarative seat policy plus matching `spec.md`/`VISION.md` revisions; provider/spend policy and OpenCode fallback viability; OMP default only after all those gates pass.
3. Phase 1 runner slices: admission/identity, execution/semaphore, receipt cache, live review proof.
4. Phase 2 boundary ADR, store, dashboard, Overmind integration.
5. Phase 3 reconciler/outbox, CI/QA input acquisition, GitHub review projection, App publisher, pre-push receipt guard, and `review-push`; advisory before protection.
6. Phase 4 responder security-boundary record, state machine, and opt-in merge policy.
7. Phase 5 packaging/auth profiles.
8. Phase 6 design/doctrine PR, separate from review-product implementation.

Each PR is independently reviewable, targets `master`, carries exact proof, and stops before merge or deploy.