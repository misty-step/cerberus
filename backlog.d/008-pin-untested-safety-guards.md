# Pin the untested safety guards with regression tests

Priority: P1 · Status: pending · Estimate: M

## Goal
Every spec falsifier and safety footgun is pinned by a test that fails if the guard is removed — closing the gaps where a silent regression currently passes green.

## Oracle
- [ ] A test spawns a child that outlives its timeout and asserts status `"timeout"` AND that the grandchild process is dead (exercises `kill_process_tree`/`setpgid`, `harness.rs:871,883` — currently zero coverage).
- [ ] Bounded-output is proven on the production path `read_capped_file` (`harness.rs:918`), not the `#[cfg(test)]` reimplementation `cap_bytes` (`:899`); the >64MB truncation branch executes in a test.
- [ ] `external_research = RequireCitations` enforcement (`validation.rs:178-184`) has a test that fails without it.
- [ ] Each `validate_request` reject branch (`validation.rs:65-92`), including `DiffDigestMismatch`, has a test.

## Verification System
- Claim: removing any safety/validation guard breaks at least one test.
- Falsifier: today, deleting `setpgid`/`kill(-pid)`, swapping `read_capped_file`, removing the `RequireCitations` branch, or removing `DiffDigestMismatch` leaves all tests green.
- Driver: `cargo test --locked` + `./scripts/verify.sh`.
- Grader: mutation check — comment out each guard, confirm a test fails.
- Evidence packet: new test names + a short mutation-survival note.
- Cadence: CI on every push (gate already runs on push + PR, `verify.yml`).

## Children
1. Timeout/orphan-child-kill test (lane-safety's "most dangerous gap").
2. Bounded-output: delete `cap_bytes`; drive a >64MB (or cap-injected) file through `read_capped_file`.
3. `RequireCitations` enforcement test.
4. Table-driven `validate_request` rejection tests, one per `ValidationError` variant.
5. (Defense-in-depth) Warn/deny when `--allow-env` forwards `GH_TOKEN`/`AWS_*`/`*_API_KEY`.

## Notes
**Why:** lane-safety guard table (vetted) — guards 2,3,6,7,8,10,11 are genuinely PINNED (credit due), but #12 (orphan-kill) and #13 (bounded-output prod path) are UNTESTED, and #5 (citations) plus parts of #1 (request rejects, incl. the `DiffDigestMismatch` tamper check) are ASSERTED-BUT-UNTESTED. Lead vet confirmed the only timeout test uses a fast command (`harness.rs:1504`) and `cap_bytes` is `#[cfg(test)]`-only. Most dangerous: an LLM CLI spawns its own subprocesses with allowlisted creds; a silent `setpgid`/`kill` regression orphans a secret-holding process running unbounded after Cerberus reports done — violating VISION's non-negotiable "no orphan children / bounded time." All cheap, all high-value.
