# ADR 001: Agentic Review Architecture for Secure PR Analysis

- Status: Accepted
- Date: 2026-02-08
- Deciders: Cerberus maintainers
- Related: #51, #52

## Decision Context

Cerberus currently renders the full PR diff into `templates/review-prompt.md` as `{{DIFF}}`, then passes the rendered prompt to Kimi CLI from `scripts/run-reviewer.sh`.

This caused two problems:

1. Large diffs hit OS argument-size limits (`ARG_MAX`) in issue #51 (quick workaround in #52).
2. The architecture is not truly agentic because the model is handed a pre-baked diff blob instead of exploring repo context intentionally.

We want agentic reviewers to inspect full repository context while preserving GitHub Actions security boundaries for untrusted PR input.

### Security Constraints

- PR titles, descriptions, branch names, and code are untrusted input.
- Reviewer jobs run with secrets (Kimi API key), so arbitrary shell execution materially increases exfiltration risk.
- `GITHUB_TOKEN` should be least privilege per job.
- Prefer `pull_request` (not `pull_request_target`) for untrusted PR code paths.

## Options Considered

| Option | Security posture | Agent capability | Complexity | How security-conscious orgs handle this |
|---|---|---|---|---|
| A. Agent uses `gh` directly via shell + scoped token (`contents:read`, `pull-requests:read`) | Medium-Low. Read-only token limits write impact, but arbitrary shell + prompt injection can still exfiltrate secrets/API keys or data. | High. Agent can fetch anything it can script. | Low-Medium. Minimal implementation changes. | Commonly avoided unless execution is strongly sandboxed and secrets are removed. |
| B. Trusted pre-fetch + mount context bundle; agent reads local files only | High. No GitHub token exposed to model runtime; shell can remain disabled. | Medium-High. Full repo plus curated PR context; no live API discovery. | Medium. Requires bundle format + prompt changes. | Very common pattern: untrusted analysis with read-only data artifact handoff. |
| C. Read-only GitHub MCP/tool server (typed ops, no shell) | High. No arbitrary command execution; server enforces allowlist. | High. On-demand retrieval with safer affordances. | High. Requires tool server integration, auth brokering, and logging. | Increasingly common in enterprise AI tooling (tool gateways over raw shell). |
| D. Sandboxed shell (container/seccomp, strict egress) | Medium-High if isolation is correct; Medium if misconfigured. Hard to get right on hosted runners. | High. Keeps shell flexibility. | High-Very High. Networking constraints conflict with model API requirements; harder debugging. | Used by mature/self-hosted platforms with dedicated sandbox infra. |
| E. Hybrid: B now, C next (and keep shell off by default) | High now, with path to high-capability tooling later. | High over time. Immediate repo exploration + later on-demand API access. | Medium now, High later. | Aligns with staged hardening used in secure CI programs. |

## Decision

Adopt **Option E (Hybrid)**.

### Phase 1 (immediate): secure agentic-by-default without shell

1. Keep reviewer shell tool disabled (`exclude_tools` remains).
2. In a trusted setup step, fetch PR context using `gh` with **read-only** token scopes only:
   - `contents:read`
   - `pull-requests:read`
3. Build a local context bundle (for example under `/tmp/cerberus-context/`):
   - `pr-context.json` (title/author/branches/body)
   - `diff.patch` (full patch)
   - `changed-files.json` (normalized file list + status)
   - optional per-file patch chunks for faster targeted reads
4. Remove inline `{{DIFF}}` prompt substitution; prompt points the agent to context bundle paths and repository files.
5. Explicitly drop `GH_TOKEN` and any non-required env vars before `kimi` invocation.
6. Split permissions by responsibility:
   - reviewer jobs: read-only GitHub permissions
   - comment/verdict posting job: `pull-requests:write`

### Phase 2 (follow-up): add safe on-demand GitHub access

Introduce a read-only MCP/tool broker exposing a narrow allowlist (`pr view`, `pr diff`, changed-files metadata, file-at-ref reads) with request/response logging and no raw token exposure to the model.

## Consequences

### Positive

- Eliminates `ARG_MAX` class from prompt argument expansion.
- Stronger defense against prompt-injection-driven command execution.
- Preserves thorough review quality by enabling full repo exploration.
- Better least-privilege alignment with GitHub Actions security guidance.

### Negative / Tradeoffs

- Additional implementation work to define and maintain the context bundle contract.
- Slightly less flexibility than raw shell until MCP/tool broker lands.
- More workflow complexity due to permission-split jobs.

### Risks and Mitigations

- Risk: oversized context artifacts on very large PRs.
  - Mitigation: size caps, truncation markers, and explicit warning annotations.
- Risk: unsafe path handling in changed file manifests.
  - Mitigation: normalize paths, reject traversal (`..`), and enforce repo-root confinement.
- Risk: accidental permission regression in workflows.
  - Mitigation: CI checks that assert required/forbidden permissions in templates and action docs.

## Reviewer Reaction Plan (for implementation PRs)

- APOLLO (correctness): call out behavior-preserving guarantees and add tests for empty diff, huge diff, and normal PR paths.
- ATHENA (architecture): include a short trust-boundary diagram in PR descriptions (prefetch stage vs reviewer stage vs reporter stage).
- SENTINEL (security): explicitly document why shell remains disabled, where tokens are scrubbed, and how path normalization blocks traversal.
- VULCAN (performance): include before/after timings and context-bundle size metrics; show caps/truncation behavior for very large diffs.
- ARTEMIS (maintainability): document context-bundle schema and keep parsing/generation logic in small, testable helpers.

Implementation PR descriptions should include:

1. Permissions before/after (`contents`, `pull-requests`) by job.
2. Exact trust boundary changes (which step can access `GH_TOKEN`, which cannot).
3. New/updated regression tests and what attack/regression each test prevents.
4. Any residual risks left intentionally for follow-up issues.

## Follow-up Work Needed

1. Implement context-bundle generation and prompt refactor to remove inline diff injection (`#54`).
2. Enforce reviewer-job least-privilege permissions and move write operations to reporter/verdict stage (`#55`).
3. Add security regression tests ensuring shell remains disabled and tokens are not passed to model runtime (`#56`).
4. Prototype read-only GitHub MCP/tool broker and evaluate capability lift vs. complexity (`#57`).

## References

- GitHub Docs: Automatic token authentication and `permissions` least privilege  
  https://docs.github.com/actions/security-for-github-actions/security-guides/automatic-token-authentication
- GitHub Docs: Security hardening for GitHub Actions (untrusted input, script injection, `pull_request_target` cautions)  
  https://docs.github.com/actions/security-guides/security-hardening-for-github-actions
- GitHub Security Lab: Preventing pwn requests (split untrusted/privileged workflow pattern)  
  https://securitylab.github.com/resources/github-actions-preventing-pwn-requests/
- GitHub Docs: Dependabot-triggered workflows run with read-only token and no secrets by default  
  https://docs.github.com/code-security/dependabot/troubleshooting-dependabot/troubleshooting-dependabot-on-github-actions
