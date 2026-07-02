# Isolate untrusted-PR review: scoped ephemeral credential + light container

Priority: P1 · Status: ready · Estimate: L · Factory epic: 4 · Shape: docs/plans/013-container-isolation.html

## Goal
Let a fully-capable Cerberus agent review UNTRUSTED third-party PRs safely by breaking the lethal trifecta at the cheapest leg — make the model credential *worthless* (per-review, capped, revoked) rather than hiding a powerful one — with a lightweight container for non-credential damage.

## Non-Goals
- Not a hosted multi-tenant service (local/CI spawns a container behind the same kernel).
- Not for trusted self-review (that stays on the local/worktree harness).
- Never call the local/un-scoped path "untrusted-safe."

## Oracle
- [ ] Each untrusted review mints a per-review OpenRouter key with a ~$5 USD `limit` (wiggle-room starting value, right-sized later from cost telemetry) via the provisioning API, injects it, and `DELETE`s it on teardown.
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
1. **M1 scoped-key lifecycle (Factory priority) — code landed, live-API proof outstanding:** mint-cap-use-revoke + crash-safe teardown (`Drop`/finally) + orphan-key sweeper. Testable without a container. See status below.
2. **M2 lightweight container (depth):** `container-opencode` substrate — `.git`-less archive mount, host not mounted, non-model egress blocked, internal network; red-team fixture family (DNS/endpoint/output/file-write/worktree-escape) for non-credential damage.
3. **M3 optional upgrades:** key-out proxy (B, providers without scoped keys) or managed sandbox (D, microVM-grade) behind the same seam — no schema change.

### M1 status (2026-07-01)
Implemented in `src/openrouter_keys.rs` (+ CLI wiring in `src/main.rs`, `review`/`review-diff`/`review-pr`):
- `ProvisioningClient::{mint_key, revoke_key, list_keys}` against OpenRouter's provisioning API (POST/GET/DELETE `/api/v1/keys`), `ScopedKeyGuard` (RAII, `Drop` revokes on any early return or panic within-process, idempotent on double-revoke), `sweep_orphaned_keys` (name-prefix + age, `cerberus-review-<unix-ts>-<tag>`), `mint_review_key` (sweep-then-mint entry point).
- CLI: `--openrouter-scoped-key` (off by default, trusted self-review unaffected) + `--openrouter-provisioning-key-file`/`-env` (explicit-only, no ambient fallback — house `--gh-token-file`/`-env` pattern) + `--openrouter-key-limit-usd` (default 5.0) + `--openrouter-orphan-sweep-seconds` (default 1800).
- 13 unit tests against a hand-rolled TCP mock server (no new test-infra dependency) cover mint/revoke/list/sweep/guard-drop/double-revoke/sweep-then-mint ordering/sweep-failure-doesn't-block-mint. `verify.sh` covers the CLI-level explicit-source refusal (no source / both sources) end-to-end through the real binary.
- **Residual, not yet proven:** the steal-and-replay probe and the crash-injection drill (oracle items 1–3) both need a real OpenRouter provisioning key, which this environment doesn't have — nobody has run mint→leak→teardown→replay-fails against the live API, or SIGKILL-mid-review→next-run-sweeps against a live key. Do this before flipping the flag on in any untrusted-PR deployment (BB epic 5). Don't check the oracle boxes above until that live run happens.
- **Not wired:** the MCP `review_git_range` tool (`src/mcp.rs`) has its own arg-parsing path and doesn't get `--openrouter-scoped-key` (or even the existing `require_child_env_for_substrate` preflight) — follow-up if/when MCP becomes an untrusted-PR entry point.
- **Discovered, not used:** OpenRouter's create-key request now appears to accept an `expires_at` field (real native TTL), contradicting the plan's "no TTL" premise from 2026-06-23 — found via docs research 2026-07-01, not verified against the live API. Worth adding as defense-in-depth once M1's live-API pass confirms the field, but the mint-cap-use-revoke+sweep design here doesn't depend on it.

## Notes
**Why:** shaped over two adversarial rounds (2026-06-22/23). Round 1 critic killed the egress-allowlist + key-in-container design (DNS bypasses a CONNECT proxy; the allowlisted model endpoint is itself an exfil sink while the agent holds a valuable key; transform-denylist scrub is unwinnable; a `git worktree` mount is a host `.git` handle). Round 2 (premise challenge + research) reframed via the lethal trifecta (Willison): break the *value* leg with a scoped ephemeral key — Anthropic's production pattern for Claude Code sandboxing — which dissolves the round-1 attacks (a worthless key isn't worth tunneling, and can't outspend its cap before revocation). Grounded: OpenRouter provisioning API supports per-key USD cap + DELETE; a 2026-07-01 docs pass suggests `expires_at` may now exist too (unverified live) — see M1 status. Key-out proxy demoted to an option; tool-execution split (C) is the north-star architecture. Trusted self-review unaffected. Full design + design-space table in the linked HTML plan.
