# Cerberus Review: WARN

**Artifact:** `artifact-github-pr-466-c54e947a`  
**Request:** `github-pr-466-c54e947a9aa1`  
**Lifecycle:** `Completed`

## Summary

**Self-review tracer bullet: harness grants full toolset; permission config does not honor external_research policy**

This PR reshapes the backlog around a VISION.md north star and lands the self-review tracer bullet: the OpenCode review agent is empowered to explore autonomously (bash/git/web, no read budget) and the prompt is rewritten to encourage thorough, grounded review. The code surface is small and clean. The schema change making Edit.replacement optional is backward-compatible and has only one construction site, which was updated. The prompt change drops the fixture-era eight-read cap. One defense-in-depth gap warrants a WARN: write_opencode_config unconditionally grants webfetch/websearch (and edit/bash) regardless of request.policy.external_research, so when external_research is Forbid the only enforcement is the prompt instruction. This is acknowledged in-code and deferred to backlog 013 (container isolation), but the permission layer currently provides no guardrail.

### Analysis

Inspected src/harness.rs (write_opencode_config, run_command_substrate, RunWorkspace isolation), src/prompt.rs (build_opencode_message rewrite + tests), src/schema.rs (Edit.replacement -> Option<String>), and confirmed via ripgrep that no other code reads Edit.replacement or .edits (render.rs, validation.rs, post.rs, receipt.rs, kernel.rs, main.rs have no consumers). The single Edit construction in prompt.rs:465 was updated to Some(...). Fixture dir has no replacement references. The env scrubbing (env_clear + allowlist), trusted PATH resolution, disposable detached worktree, and private permissions (0o600/0o700) provide solid substrate isolation. The unconditional tool grants are the one substantive concern: external_research policy is enforced at validation.rs:178 (RequireCitations) and surfaced in render.rs, but write_opencode_config never consults it, so web tools remain permitted at the permission layer even when policy is Forbid. For trusted self-review dogfooding this is acceptable; for the general path it is a prompt-only guard until 013 lands.

## Context Capabilities

- diff: `true`
- repo_head: `true`
- repo_base: `false`
- local_runtime: `false`
- remote_runtime: `false`
- external_research: `Forbid`

## Findings

### [minor] OpenCode permission config grants web tools unconditionally, ignoring external_research policy

**Category:** `security`  
**Confidence:** `0.80`  
**Anchors:** src/harness.rs:349  

write_opencode_config always sets webfetch/websearch (and edit/bash) to "allow" without consulting request.policy.external_research. When a request sets external_research to Forbid (as this very request does), the agent is told via the prompt not to do network research, but the permission layer still permits webfetch/websearch. A model that ignores or misreads the prompt could perform network egress or fetch arbitrary URLs. The code comment and PR description explicitly defer untrusted-PR network/credential isolation to backlog 013 (container profile), so this is an acknowledged, deferred gap rather than an oversight — but until 013 lands the only enforcement of external_research=Forbid is prompt wording, which is not a hard guardrail. Defense-in-depth would be improved by gating webfetch/websearch on the external_research policy (or at least on a harness-level trust flag) so the permission layer refuses network tools when policy forbids them.

Evidence: src/harness.rs write_opencode_config builds the permission object with static "webfetch": "allow" and "websearch": "allow" (and "bash": "allow", "edit": "allow") and never reads request.policy.external_research. By contrast, external_research IS consulted elsewhere: validation.rs:178 enforces RequireCitations, and render.rs:28 surfaces it. The policy value Forbid is therefore enforced only by the master prompt instruction, not by the substrate permission config.

## Comments

- `C1` src/harness.rs:349: These four "allow" values are granted unconditionally. Consider gating webfetch/websearch on `request.policy.external_research != ExternalResearchPolicy::Forbid` so the permission layer honors the request policy even before container isolation (013) lands. bash/edit are needed for autonomous exploration but web tools are exactly what external_research=Forbid is meant to suppress.
- `C2` src/schema.rs:406: Schema change is clean: Edit.replacement moved from String to Option<String> with #[serde(default, skip_serializing_if = "Option::is_none")]. Old artifacts with a string value still deserialize (Option accepts a present string), and new artifacts omit the field when absent. Confirmed no other code reads Edit.replacement or .edits (render.rs/validation.rs/post.rs/receipt.rs/kernel.rs/main.rs have no consumers); the single construction site at prompt.rs:469 was updated to Some(...).
- `C3` src/harness.rs: Substrate isolation is otherwise solid: env_clear + explicit allowlist, trusted PATH resolution (resolve_executable_in rejects relative/non-bare binaries), disposable detached git worktree with Drop cleanup, and private file/dir permissions (0o600/0o700). The full-toolset grant is the intended design for autonomous self-review; the only gap is that the grant is not conditioned on the external_research policy.

## Residual Risk

- Did not run cargo build/test/clippy (local_runtime is false); compile correctness is inferred from source inspection only.
- Did not review the full VISION.md, backlog.d/006-013, or docs/plans/006 HTML for content accuracy; focused on code.
- Did not inspect opencode's actual handling of permission.bash/webfetch values against the opencode version in use; assumed the granted permissions are honored as written.
- Container/network isolation for untrusted PRs (backlog 013) is not yet implemented; the current substrate relies on env scrubbing + disposable worktree only.

## Receipts

- `receipt-master` Master via `opencode`: Completed
