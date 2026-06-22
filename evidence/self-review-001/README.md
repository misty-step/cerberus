# Self-review proof-of-life — evidence packet 001

First time Cerberus reviewed a real pull request with a real model, end to end.

- **PR:** [misty-step/cerberus#466](https://github.com/misty-step/cerberus/pull/466), head `c54e947a`
- **Substrate / model:** OpenCode `1.2.6` + `openrouter/z-ai/glm-5.2`, single master agent (no subagents)
- **Context tier:** `repo_head` — the agent explored a disposable worktree of the full repo + history (read/grep/git), not just the diff. `files_reviewed` spans `harness.rs`, `prompt.rs`, `schema.rs`, `validation.rs`, `post.rs`, `render.rs`, docs.
- **Verdict:** `WARN`, lifecycle `completed`, `ReviewArtifact.v1` validation **passed**, latency ~132s.
- **Posted to GitHub:** commit status (`Cerberus Review: success / WARN`), a summary comment, and inline review comments on changed lines.
- **Idempotent:** a second `--post` on the frozen head issued `PATCH update-summary-comment` (one comment, `updated_at` advanced), not a duplicate.

## Files
- `artifact.json` — the validated `ReviewArtifact.v1`
- `review.md` — rendered Markdown (what the summary comment carries)
- `post-plan.json` / `post-result.json` — the GitHub projection plan and the applied result
- `receipt-bundle.json` — redacted `ReviewReceiptBundle.v1` for upstream scoring (Daedalus)
- `execution_plan.json` — the redacted substrate command
- `transcript.txt` — the full agent session (proof of real exploration: git/grep/read tool calls)

## What the run taught us (dogfound, fixed or logged)
1. **Fixed:** `Edit.replacement` was a required `String`; real models emit instruction/diff fixes with no replacement → made it `Option<String>` (commit on this branch).
2. **Fixed:** with no exploration budget the agent explored to the wall-clock and never emitted an artifact (1 of 3 runs) → added convergence pressure to the prompt (132s after the fix).
3. **Logged (backlog 007):** the substrate grants `webfetch`/`websearch` regardless of `request.policy.external_research` (`forbid` here) — Cerberus reviewed its own PR and flagged this in its own change.
4. **Logged (backlog 006/013):** with `bash` + the key in the child env, an untrusted PR could exfiltrate the credential — the agent independently rediscovered the threat the container profile (013) addresses.
