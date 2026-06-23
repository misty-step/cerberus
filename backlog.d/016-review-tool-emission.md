# Emit the review via a Cerberus MCP tool surface (not a JSON-blob message)

Priority: P1 · Status: pending · Estimate: M

## Goal
Stop fighting the model into a JSON blob. The agent records its review by calling Cerberus-provided MCP tools (`submit_finding`, `submit_comment`, `submit_fix`, `set_summary`, `submit_review`) whose argument schemas enforce `ReviewArtifact.v1` structure natively and validate in-loop — the agent's own primitive (tool-calling), not a prose contract.

## Non-Goals
- The artifact CONTRACT (`ReviewArtifact.v1`) stays; only the EMISSION mechanism changes.
- Not `response_format`/structured-output — OpenCode doesn't expose it (verified). Tool-calling is the native, in-loop path: config `mcp.<name>.type=local` (verified present in the OpenCode config schema).

## Oracle
- [ ] Cerberus runs a local MCP server (e.g. `cerberus review-tools --out <artifact-path>`), registered in the generated `opencode.json` as `mcp.cerberus-review = { type: "local", command: [...], enabled: true }`.
- [ ] The server exposes review-submission tools whose arg schemas are the `ReviewArtifact.v1` field shapes; it assembles the artifact from the calls and writes it to `<artifact-path>` on `submit_review`.
- [ ] The master prompt instructs the agent to record its review via the tools; the ~1800-char JSON-shape lecture is gone.
- [ ] The marker / XML / raw-JSON fallback parser in `harness.rs` is deleted; the harness reads the artifact from `<artifact-path>` and validates it.
- [ ] In-loop feedback: a `submit_finding` whose anchor doesn't resolve returns an error to the agent (using 007's resolver); the agent self-corrects within the run.
- [ ] Schema drift like the `Edit.replacement` null cannot recur — enforced at tool-call decode.

## Notes
**Why:** ADR 0003 + operator insight (2026-06-23): don't fight the model into a JSON blob — give it tools, its native primitive. Verified OpenCode supports local MCP servers (`mcp.local.command`). Tool-arg schemas give the same structural guarantee as structured output but **in-loop**, and in-loop anchor-resolution feedback makes groundedness a *tool property* (composes with **007**, the resolver) rather than a post-hoc Rust gate. Deletes the prose contract AND the defensive parser (delete-first). Supersedes the earlier "structured output via `response_format`" framing, which OpenCode can't do. Build needs a Rust MCP server (e.g. the `rmcp` SDK) + tool schemas + state assembly + prompt rewrite + harness wiring.
