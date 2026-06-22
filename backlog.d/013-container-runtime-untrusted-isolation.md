# Container runtime for untrusted-PR review isolation

Priority: P1 · Status: ready · Estimate: L · Shape: docs/plans/013-container-isolation.html

## Goal
Let a fully-capable Cerberus agent review UNTRUSTED third-party PRs without the model credential ever being obtainable or exfiltrable — by keeping the key out of the container, not by trusting an egress filter.

## Non-Goals
- Not a hosted multi-tenant service (local/CI spawns a container behind the same kernel).
- Not for trusted self-review (that stays on the local/worktree harness; key-in-env is fine for our own code).
- Never sell any key-in-container or local path as "untrusted-safe."

## Oracle
- [ ] A `--harness container-opencode` review runs in Docker on an internal network with the disposable tree mounted as a `.git`-less `git archive` extract (NOT a linked worktree), host checkout never mounted.
- [ ] `printenv` inside the container shows NO `OPENROUTER_API_KEY`; the model call still succeeds via a key-injecting sidecar that holds the key.
- [ ] No in-container resolver: zero outbound UDP/53; only sidecar/model egress in the network log.
- [ ] A red-team fixture FAMILY (DNS exfil, endpoint-as-sink, output-encoding, file-write, worktree-escape) all fail to surface the key; the key value + transforms appear in no output/artifact/written file.
- [ ] Host checkout digest unchanged after the run; a normal review still yields a valid `ReviewArtifact.v1`.

## Verification System
- Claim: a prompt-injected agent on an untrusted PR cannot obtain or exfiltrate the model credential by any vector, because it is never in the container.
- Falsifier: any red-team fixture surfaces the key; the key is found in container env/fs; the mounted tree has `.git`; the host checkout mutates; a clean review can't produce a valid artifact.
- Driver: the red-team family through `--harness container-opencode` with network capture + in-container key-absence probe + output key-scan.
- Grader: network log (no UDP/53, only model egress) + key-absence probe + key-scan (literal & transforms) + host-tree digest + artifact validation. One canned fixture is insufficient — grow the family on each near-miss.
- Evidence packet: network capture, fixture family, key-absence probe, container execution plan under `target/cerberus/container-*`.
- Cadence: gated in `verify.sh` when Docker present; on every change to the container/proxy/mount path.
- Gaps/waiver: "untrusted-safe" attaches only to key-out + no-resolver + clone-not-worktree (M1+M2); M3 egress-allowlist/scrub is depth. The model-domain pin must track the provider's hosts.

## Children
1. **M1 harness:** `container-opencode` substrate (docker run, internal network, `.git`-less tree mount, host not mounted), failing closed; the red-team fixture family; pinned Dockerfile (opencode + git + rg + ast-grep).
2. **M2 key-out (floor):** key-injecting sidecar (key never in container) + no in-container resolver. Earns the untrusted-capable label.
3. **M3 depth:** domain egress-allowlist at the sidecar + structural artifact-field validation (entropy/length) + backstop scrub for any other secrets.

## Notes
**Why:** surfaced by the tracer-bullet (PR #466) critique; shaped 2026-06-22. A security critic dismantled the first design (egress-allowlist + key in container): DNS bypasses a CONNECT proxy, and the one allowlisted host (the model API) is itself an exfil sink while the agent holds the key — so egress filtering is ~zero protection for untrusted code; a transform-denylist output scrub is unwinnable; the mounted `git worktree` is a live handle to the host `.git` (verified). Hence **key-out is the floor, not optional**. Trusted self-review is unaffected (stays local). Full design + alternatives + red-team verification in the linked HTML plan.
