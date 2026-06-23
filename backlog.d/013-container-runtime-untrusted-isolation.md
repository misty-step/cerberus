# Isolate untrusted-PR review: scoped ephemeral credential + light container

Priority: P1 · Status: ready · Estimate: L · Shape: docs/plans/013-container-isolation.html

## Goal
Let a fully-capable Cerberus agent review UNTRUSTED third-party PRs safely by breaking the lethal trifecta at the cheapest leg — make the model credential *worthless* (per-review, capped, revoked) rather than hiding a powerful one — with a lightweight container for non-credential damage.

## Non-Goals
- Not a hosted multi-tenant service (local/CI spawns a container behind the same kernel).
- Not for trusted self-review (that stays on the local/worktree harness).
- Never call the local/un-scoped path "untrusted-safe."

## Oracle
- [ ] Each untrusted review mints a per-review OpenRouter key with a USD `limit` (provisioning API), injects it, and `DELETE`s it on teardown.
- [ ] **Steal-and-replay:** a key captured mid-run FAILS after teardown (401 revoked / 402 over-cap); the minted key GET returns 404/disabled.
- [ ] **Crash safety:** killing the run mid-review leaves no usable key — an orphan-key sweeper revokes review-tagged keys on the next run.
- [ ] The container blocks non-model egress (`curl evil.com` fails), mounts a `.git`-less `git archive` tree (not a worktree), never mounts the host checkout; host digest unchanged.
- [ ] A normal review still yields a valid `ReviewArtifact.v1`; `verify.sh` green (container path skipped without Docker).

## Verification System
- Claim: a prompt-injected agent on an untrusted PR cannot obtain a credential worth stealing or reach a non-model host; any credential it captures is capped and revoked by run-end.
- Falsifier: the minted key outlives the run; the key has no cap; a stolen key still works post-run; the agent reaches a non-model host; the host checkout mutates; a clean review can't produce a valid artifact.
- Driver: steal-and-replay probe + crash-injection (kill mid-run → sweeper revokes) + red-team container family with egress capture.
- Grader: post-run the minted key is dead (API) and was capped; egress log model-only; host-tree digest unchanged; artifact validates.
- Evidence packet: key create/delete transcript, steal-and-replay result, crash-sweeper log, egress capture under `target/cerberus/container-*`.
- Cadence: key-lifecycle tests always; container red-team gated on Docker in `verify.sh`; on every change to the credential/sandbox path.
- Gaps/waiver: residual = a stolen key usable for seconds up to the cap until DELETE; accepted. Provisioning key is secret-zero (host-side). Provider lock-in → option B (key-out proxy) fallback.

## Children
1. **M1 scoped-key lifecycle (floor):** mint-cap-use-revoke + crash-safe teardown (`Drop`/finally) + orphan-key sweeper + the steal-and-replay probe. Testable without a container.
2. **M2 lightweight container (depth):** `container-opencode` substrate — `.git`-less archive mount, host not mounted, non-model egress blocked, internal network; red-team fixture family (DNS/endpoint/output/file-write/worktree-escape) for non-credential damage.
3. **M3 optional upgrades:** key-out proxy (B, providers without scoped keys) or managed sandbox (D, microVM-grade) behind the same seam — no schema change.

## Notes
**Why:** shaped over two adversarial rounds (2026-06-22/23). Round 1 critic killed the egress-allowlist + key-in-container design (DNS bypasses a CONNECT proxy; the allowlisted model endpoint is itself an exfil sink while the agent holds a valuable key; transform-denylist scrub is unwinnable; a `git worktree` mount is a host `.git` handle). Round 2 (premise challenge + research) reframed via the lethal trifecta (Willison): break the *value* leg with a scoped ephemeral key — Anthropic's production pattern for Claude Code sandboxing — which dissolves the round-1 attacks (a worthless key isn't worth tunneling, and can't outspend its cap before revocation). Grounded: OpenRouter provisioning API supports per-key USD cap + DELETE but NO TTL, so revocation must be crash-safe. Key-out proxy demoted to an option; tool-execution split (C) is the north-star architecture. Trusted self-review unaffected. Full design + design-space table in the linked HTML plan.
