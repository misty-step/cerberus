# Container runtime for untrusted-PR review isolation

Priority: P1 · Status: pending · Estimate: L

## Goal
Give Cerberus a container execution profile so a fully-capable review agent (bash, git, network) can review UNTRUSTED third-party PRs without the host credentials or arbitrary network being reachable for exfiltration.

## Non-Goals
- Not a hosted multi-tenant service (still local/CI spawning a container behind the same kernel).
- Not required for self-review of our own trusted code (that is 006, worktree-only).

## Oracle
- [ ] A `--harness opencode` run can execute inside a rootless container (Podman/Docker) behind the same `ReviewKernel`/`ReviewSubstrate` contract — no public schema change.
- [ ] Network-egress allowlist: the model/provider endpoint is reachable; arbitrary outbound (e.g. `curl evil.com`) is denied.
- [ ] `OPENROUTER_API_KEY` and any provider cred are not readable by the agent's shell — provided to the provider layer only (OpenCode auth store or an egress proxy), never as a bash-inheritable env var.
- [ ] An adversarial fixture PR that attempts prompt-injection exfiltration (a diff instructing the agent to print/exfil env or curl it out) cannot reach the key or arbitrary network.
- [ ] The worktree mount is the only writable path; the host checkout is not mounted writable.

## Verification System
- Claim: an untrusted PR cannot make the review agent exfiltrate host credentials or reach arbitrary network destinations.
- Falsifier: the injection fixture exfiltrates the key, arbitrary egress succeeds, or the host checkout is mutated.
- Driver: the injection fixture through the container harness + an egress-allowlist probe.
- Grader: key never leaves; only allowlisted egress succeeds; host untouched.
- Evidence packet: container execution plan + injection-fixture transcript + egress-probe result.
- Cadence: pre-merge for this profile; CI once stable.

## Notes
**Why:** the 006 self-review tracer bullet runs a fully-capable agent (bash/git/web, no exploration cap) because reviewing our OWN code is trusted and the worktree is disposable. The moment a consumer (Bitterblossom, Olympus/Argus) points Cerberus at an untrusted third-party PR, that same capability + `OPENROUTER_API_KEY` in env is an exfiltration path (surfaced by adversarial critique during 006 shaping). Tool-denial is the wrong fix — it guts the reviewer; the right boundary is container network-egress isolation + credential handling. `spec.md` already lists "rootless container runtime profile" as Post-MVP behind the same kernel contract, and the operator wants it soon. This is the security boundary for the consumer use case, decoupled from the dogfood so 006 can ship now.
