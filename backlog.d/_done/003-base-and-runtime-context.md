# Add base checkout and runtime context tiers

Priority: P1 | Status: shipped | Estimate: L

## Goal

Let Cerberus use richer available context by supporting base+head workspace
comparison and explicit local/runtime probes without overstating evidence.

## Oracle

- [ ] `ReviewRequest.v1` producers can include both base and head workspaces
  when the caller supplies safe paths or refs.
- [ ] The harness creates isolated disposable workspaces for both base and
  head and records `repo_base: true` only when base inspection is available.
- [ ] Runtime targets execute only when policy explicitly allows them, with
  bounded env, cwd, timeout, and transcript capture.
- [ ] Artifacts that claim base or runtime evidence without matching request
  capabilities fail validation.

## Verification System

- Claim: Cerberus can compare base and head context and run allowed probes
  while preserving capability truth.
- Falsifier: a diff-only request produces `repo_base: true`; a runtime command
  runs without explicit policy; runtime output leaks unallowed env; a base
  workspace mutation touches the user's checkout.
- Driver: `./scripts/verify.sh` plus fixture requests for diff-only,
  repo-head, base+head, and local-runtime modes.
- Grader: execution plans, artifact capabilities, runtime transcripts, and
  validation failures for overstated capabilities.
- Evidence packet: `target/cerberus/context-tiers/*`.
- Cadence: before enabling runtime-aware review in a caller or poster.

## Children

1. Add `--base-workspace`/`--base-ref` acquisition for git-range and PR
   requests.
2. Extend `RunWorkspace` to manage base and head worktrees safely.
3. Add explicit local runtime policy fields and a minimal command probe runner.
4. Teach prompts to compare base/head and cite runtime evidence only when
   capability flags allow it.
5. Add fixture coverage for all context tiers.

## Notes

**Why:** The spec already defines `repo_base_and_head`, `local_runtime`, and
`remote_runtime`, but the shipped implementation only proves diff and
repo-head review. This closes the highest-value evidence gap without turning
Cerberus into a hosted platform.

**Evidence:** `./scripts/verify.sh` exercises base+head disposable worktrees,
local runtime policy rejection, allowlisted runtime env capture, runtime
transcript availability to OpenCode, and capability-overstatement rejection.
