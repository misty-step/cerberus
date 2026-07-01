# Agent-native review handoff: spawn Cerberus, get the review back, branch on it

Priority: P1 · Status: shipped · Estimate: M · Shape: docs/plans/018-agent-native-handoff.html

**Shipped 2026-06-26:** PR #479 landed `review-diff`, verdict-gated exit codes,
README handoff docs, and `./scripts/verify.sh` coverage for the agent-native
CLI contract. Factory groom 2026-07-01 moved this file to `_done/` to remove
active-backlog drift while preserving the original shape.

## Goal
Make Cerberus's **primary** form factor first-class: a calling agent (or human, or CI) spawns Cerberus on a local diff, reads the review off stdout, and branches on a **verdict-gated exit code** — no GitHub, no token, no intermediate request file.

## Why
This is how Cerberus is actually used on our own repos: an agent working in the repo dispatches Cerberus as a subprocess, gets a review of the current changes, and decides what to fix / whether it's blocking. The engine already produces the review (`cerberus review` → `ReviewArtifact.v1` + `render_markdown`); the gaps are (1) `review` exits `0` even on a `FAIL` verdict, so an agent can't gate without parsing, and (2) reviewing a local range is a two-command dance (`request git-range … > req.json` then `review --request req.json`). Prior art is unanimous (reviewdog `-fail-level`, linters, Claude Code hooks): **structured result + a severity-gated exit code** is the agent/CI contract. GitHub posting stays the secondary, consumer-owned path (see reshaped 014); this ticket is the engine's native handoff. Per spec.md (artifact is caller-neutral; renderers project out) and VISION.

## Non-Goals
- No GitHub, no posting, no token in this path — that is 014 (consumer-owned).
- No MCP server yet. Build the CLI contract first; an MCP wrapper over it is an additive later layer, not a rewrite (benchmark: MCP costs ~4–32× the tokens for the same call). Note it as a future option, don't build it.
- **Reviewing the uncommitted working tree** (vs a committed range) is a follow-on: it needs a working-tree diff acquisition + a non-SHA isolation story. Scope 018 to a committed range (`base...head`), which covers the common "review my branch vs main before I push" flow. File the working-tree variant separately if wanted.
- No new review logic. Reuse `build_git_range_request` + `ReviewKernel` + `render_markdown`.

## Constraints (invariants that must survive)
- The `ReviewRequest.v1 → ReviewArtifact.v1` seam and `validation.rs` are unchanged.
- A Cerberus **error** (no valid artifact) must stay distinguishable from a **blocking verdict** (a successful review that found issues) — different exit codes.
- Default behavior of existing `cerberus review` stays back-compatible (no `--fail-on` ⇒ current exit behavior).
- Clean stdout: in the agent-native command, stdout carries ONLY the review (markdown or artifact JSON); logs/errors go to stderr.

## Repo Anchors
- `src/main.rs` — `Command` enum, `review()` / `review_pr()` orchestrator pattern, `fn main() -> Result<()>` (today: Err ⇒ exit 1, Ok ⇒ exit 0; no custom codes).
- `src/request.rs` — `build_git_range_request(GitRangeRequestOptions)` (does `git diff base...head`); reuse verbatim.
- `src/kernel.rs` — `ReviewKernel::review`; `src/render.rs` — `render_markdown(artifact)`.
- `src/schema.rs` — `Verdict { Pass, Warn, Fail, Skip }`.
- `scripts/verify.sh` — `expect_review_failure` checks *non-zero* (so error⇒exit 2 stays compatible); add exit-code-matrix coverage here.

## Design (chosen)

**1. Verdict-gated exit code (the core).** Add `--fail-on <none|warn|fail>` to `review` and the new `review-diff`. Exit-code contract — the load-bearing surface:

| Exit | Meaning | When |
|---|---|---|
| **0** | clean / proceed | review produced a valid artifact; verdict below the `--fail-on` threshold (or `--fail-on none`, the default) |
| **1** | blocking — read the review | review produced a valid artifact; verdict at/above the threshold (`--fail-on fail` ⇒ `FAIL`; `--fail-on warn` ⇒ `WARN`/`FAIL`) |
| **2** | Cerberus error — no review | harness/validation/IO failure; untrusted lifecycle; no valid artifact produced |

Today every error exits 1 (Rust default). Move tool errors to **2** so exit `1` can mean "blocking verdict" unambiguously. `SKIP` verdict is not "blocking" (it means couldn't review) — treat as exit 0 unless explicitly gated; the agent reads the verdict for nuance.

**2. `cerberus review-diff` (the ergonomic entry).** One command, no GitHub:
```
cerberus review-diff [--repo-path .] --base <ref> [--head HEAD] \
  [--harness opencode] [--model …] [--allow-env …] [--timeout-seconds …] \
  [--fail-on fail] [--out artifact.json] [--markdown review.md] [--json]
```
Fuses `build_git_range_request` + `ReviewKernel` + `render_markdown`. **Default: render the review markdown to stdout** (the deliverable the calling agent reads); `--json` emits the artifact JSON to stdout instead; `--out`/`--markdown` also persist to files. Exit code per the matrix.

**3. Document the contract.** A README/spec "Agent-native handoff" section: spawn → read stdout (review) → branch on exit code. The one example an orchestrating agent needs.

## Oracle (executable)
- [ ] `cerberus review-diff --repo-path <r> --base <b> --head <h> --harness fixture --fixture-output <f>` prints the rendered review to stdout, writes a valid `ReviewArtifact.v1` with `--out`, touches no GitHub and needs no token; exit 0 when verdict is below threshold.
- [ ] Exit-code matrix proven with fixtures in `verify.sh`: a `PASS` artifact ⇒ exit 0; a `FAIL` artifact with `--fail-on fail` ⇒ exit **1**; a malformed/invalid emission ⇒ exit **2** (and `--fail-on fail` on a `PASS` ⇒ 0, i.e. gating never fires on non-blocking verdicts).
- [ ] `--fail-on warn` ⇒ exit 1 on a `WARN` artifact; `--fail-on none` (default) ⇒ exit 0 even on `FAIL` (back-compat for existing `review`).
- [ ] stdout in `review-diff` contains only the review (markdown, or artifact JSON under `--json`); secret-leak/stderr checks from `verify.sh` still pass.
- [ ] `./scripts/verify.sh` green; `cerberus review-diff --help` documents `--fail-on` and the exit codes; the README/spec handoff section exists.
- [ ] Live: `cerberus review-diff --base <merge-base> --harness opencode --model … --fail-on fail` on a real local branch returns the review on stdout and an exit code an agent can branch on.

## Verification System
- Claim: a calling agent can spawn Cerberus on a local diff and get back (a) the full review on stdout and (b) a verdict-gated exit code that distinguishes proceed / blocking / tool-error — with no GitHub and no token.
- Falsifier: a blocking `FAIL` review exits 0 (agent can't gate); a tool error and a blocking verdict share an exit code (agent can't tell "broke" from "blocked"); stdout is polluted with logs; `--fail-on` defaults change existing `review` exit behavior; `verify.sh` regresses.
- Driver: the fixture exit-code matrix in `verify.sh` (PASS/WARN/FAIL × `--fail-on` × error path) + one real `review-diff` on a local branch.
- Grader: each fixture's `$?` equals the matrix; stdout-only-review check; `verify.sh` exit 0.
- Evidence packet: `target/cerberus/review-diff-*` artifacts + the captured exit codes per case.
- Cadence: the matrix in `verify.sh` always; the live run on any change to the exit-code or `review-diff` path.

## Risks + Rollout
- **Exit-code change ripple:** moving tool-errors from 1→2 could surprise a caller asserting `== 1`. `verify.sh`'s `expect_review_failure` only checks non-zero, so it's safe; audit for any `== 1` assumption. Rollback = revert; the `ReviewArtifact.v1` seam is untouched.
- **Scope drift toward an arena/eval:** keep this a dumb handoff (review + exit code). Measuring review quality is Daedalus ([[cerberus-daedalus-eval-boundary]]).
- **Naming:** `review-diff` reviews a committed `base...head` range; if "diff" misleads toward uncommitted, rename to `review-range` — the working-tree variant is a separate ticket.

## Premise Source
Operator session 2026-06-25: reframed the GitHub-App work after recognizing the agent-native subprocess handoff is the *primary* form factor and GitHub posting is a consumer-owned delivery layer (see [[cerberus-posting-boundary]]). Research lane (reviewdog/SARIF/PR-Agent/Danger/CodeRabbit/Greptile; MCP-vs-CLI benchmark) confirmed: host-neutral artifact + severity-gated exit code is the universal agent/CI contract; build the CLI before any MCP layer. Grounding: spec.md (artifact caller-neutral, posting is projection/post-MVP), VISION.md (consumer owns where results post). No durable transcript stored — explicit waiver.

## HTML Plan
`docs/plans/018-agent-native-handoff.html`
