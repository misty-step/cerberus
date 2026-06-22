# Self-review tracer bullet: Cerberus reviews its own PRs with a real GLM-5.2 agent

Priority: P0 · Status: in-progress · Estimate: M · Shape: docs/plans/006-self-review-tracer-bullet.html

## Delivery receipt (2026-06-22)
Delivered and proven live on [PR #466](https://github.com/misty-step/cerberus/pull/466) (open, pending merge). A single OpenCode + `openrouter/z-ai/glm-5.2` agent explored a `repo_head` worktree autonomously and posted a validated `WARN` review — commit status + summary comment + inline comments — in ~132s. Idempotency confirmed live: a second `--post` issued `PATCH` (one summary comment, updated, not duplicated). Evidence: `evidence/self-review-001/`. Two bugs the dogfood surfaced were fixed in-branch (`Edit.replacement` → `Option`; convergence pressure so the agent reliably emits an artifact). Two were logged: web-vs-`external_research` → ticket 007 child 6; untrusted-PR key-exfil → ticket 013. Follow-up F3 (dogfound): the prompt contract checklist (`ARTIFACT_FIELD_PATHS`) still lists `suggested_fixes[].edits[].replacement`, implying it is required after the schema made it optional — reword the contract to mark optional fields, and add a `validation` check that `format=replacement` fixes carry a replacement.

## Goal
Wire a real single OpenCode + GLM-5.2 agent into the existing `review-pr` pipeline, let it explore a Cerberus PR's worktree autonomously, and post a genuine, schema-valid, idempotent review (top-level summary + inline comments) — the first proof the reviewing brain works at all.

## Non-Goals
- No subagent orchestration / dynamic lanes yet (single master agent only).
- No container runtime yet (reuse the disposable worktree; untrusted-PR isolation is ticket 013).
- No new schema, no first-party agent loop, no automated quality scoring (that is 007 + a 006 follow-on).

## Oracle
- [ ] The agent runs with a full toolset (bash → rg/ast-grep/git, webfetch, websearch) and NO exploration cap; the generated `opencode.json` is permissive (no edit-deny / skip-permissions) and the worktree exposes full git history.
- [ ] `./scripts/verify.sh` stays green (no regression to the fixture pipeline).
- [ ] `review-pr --number <PR> --repo misty-step/cerberus --model openrouter/<glm-5.2-slug> --allow-env OPENROUTER_API_KEY --timeout-seconds 1800 --dry-run` writes an artifact that passes `ReviewArtifact.v1` validation; the operator reads it before any `--post`.
- [ ] After the human read, `--post` exits 0; the target PR shows a Cerberus summary comment AND ≥1 inline comment on a changed new-side line.
- [ ] Rerunning the exact `--post` command on the **frozen-head** PR UPDATES the summary + inline comments (no duplicates).
- [ ] Human grade: every finding's **claim** is true (not just its anchor valid); the transcript shows the agent actually used git/grep to explore beyond the diff; signal > noise.
- [ ] Evidence packet committed under `evidence/self-review-001/` (artifact, transcript, receipt-bundle, review.md, post-result).

## Verification System
- Claim: a real GLM-5.2 OpenCode agent exploring the worktree autonomously produces a valid, grounded, useful artifact for a real Cerberus PR and posts it idempotently.
- Falsifier: invalid artifact · findings cite nonexistent lines · reruns duplicate comments · agent can't auth or edits the checkout · exploration never converges within the timeout.
- Driver: the `review-pr … --post` command above, run twice.
- Grader: `ReviewArtifact.v1` validation (machine) + human read of anchor groundedness + GitHub diff showing no duplicate threads.
- Evidence packet: `evidence/self-review-001/*` + posted PR comment permalinks.
- Cadence: once now (proof-of-life); then on every prompt/model change.
- Gaps/waiver: automated groundedness enforcement + quality measurement are 007; the real container is the fast-follow; the GLM-5.2 validity rate over N runs is a 006 follow-on once one run succeeds.

## Children
1. **M0 pre-flight:** confirm the exact OpenRouter GLM-5.2 slug and that `opencode run --model openrouter/<slug> "hi"` authenticates from `OPENROUTER_API_KEY` (env-source auth verified to work — quick confirm); confirm the disposable worktree exposes full git history for `git log/blame`.
2. **M1 empower:** rewrite `build_opencode_message`/`build_master_prompt` — remove the 1-round/≤8-read/stop cap (`prompt.rs:261`); add autonomous full-repo exploration (git history, grep, ast-grep; diff is a hint) bounded by wall-clock + reviewer-craft (severity calibration, false-positive discipline, re-anchor every finding) + "converge and emit one artifact". Make `write_opencode_config` permissive (full toolset; drop edit-deny / skip-permissions). Keep the artifact contract.
3. **M2 wire+run:** branch the pending vision+groom work → PR; `--timeout-seconds 1800`; `--dry-run` + human read of artifact AND transcript, then `--post`; iterate until valid + useful.
4. **M3 idempotency+evidence:** rerun on the frozen-head PR, confirm update-not-duplicate, commit the evidence packet, extend the `verify.sh` live block to pass model + allow-env + timeout-seconds.

## Notes
**Why:** lane-substrate F1/F2/F5 — the entire green gate validates the harness *around* a reviewer that has never met a real model; the live block (`verify.sh:517`) passes neither model nor key. Reading the code for the shape surfaced the load-bearing surprise: `build_opencode_message` (`prompt.rs:261`) caps the agent at "one tool-call round, ≤8 reads, then stop" — shallow-by-design, the opposite of autonomous exploration. The pipeline (worktree, isolated env, edits-denied profile, validation, `post.rs` idempotent summary+inline) is already built and fixture-tested, so this is a prompt + wiring + real-run bullet, not new infrastructure. Tension to respect (lane-exemplars #1): more flat context can dilute attention, so budget-relaxation ships with grounding discipline and a human read; the enforced gate is 007. Adversarial critique during shaping caught the load-bearing hole: today's generated `opencode.json` denies only `edit`, leaving `bash`/network at OpenCode defaults — relaxing the prompt without M1 lockdown turns the agent into a shell that can exfiltrate the key. Open product question: the operator said "use git for base..head"; this shape instead feeds the diff (already in the request) + optional base/head worktrees and denies the shell — confirm that trade. Full design + alternatives + milestones in the linked HTML plan.
