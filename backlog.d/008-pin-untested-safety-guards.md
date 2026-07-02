# Pin the untested safety guards with regression tests

Priority: P1 · Status: oracle satisfied 2026-07-02, child 5 deferred (operator decision) · Estimate: M

## Goal
Every spec falsifier and safety footgun is pinned by a test that fails if the guard is removed — closing the gaps where a silent regression currently passes green.

## Oracle
- [x] A test spawns a child that outlives its timeout and asserts status `"timeout"` AND that the grandchild process is dead — `harness::tests::timeout_kills_the_whole_process_group_not_just_the_direct_child`. SIGKILL can't be trapped, so it uses a pid-file (grandchild backgrounds `sleep 30`, writes its own pid, gets checked via `kill(pid, 0)` after the timeout fires) rather than a trap handler. Mutation-verified: temporarily reverted `kill_process_tree` to `child.kill()` only, confirmed the test fails with the grandchild pid still alive, then restored.
- [x] Bounded-output is proven on the production path `read_capped_file` directly (no `cap_bytes` reimplementation exists in the codebase today — already gone before this ticket) — `harness::tests::read_capped_file_truncates_the_middle_of_oversized_output` writes a real 65MB file with distinguishable head/tail markers and asserts the truncation-marker branch executes and the result never exceeds `OUTPUT_CAPTURE_CAP`.
- [x] `external_research = RequireCitations` enforcement has two tests: `rejects_finding_without_citation_when_policy_requires_one` and `accepts_finding_with_citation_when_policy_requires_one`.
- [x] Every `validate_request` reject branch, including `DiffDigestMismatch`, is covered by one table-driven test (`validate_request_rejects_each_known_violation`, 8 cases, one per `ValidationError` variant `validate_request` can return) — replaces the two narrower pre-existing tests it subsumes.

Child 5 ("(Defense-in-depth) warn/deny when `--allow-env` forwards `GH_TOKEN`/`AWS_*`/`*_API_KEY`") was explicitly bracketed as defense-in-depth and is not in the oracle above; it also requires an operator judgment call (warn vs. deny, exact pattern list) rather than pure test-writing, so it's left unstarted per the overnight contract's "skip operator-decision items, note them" rule.

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
