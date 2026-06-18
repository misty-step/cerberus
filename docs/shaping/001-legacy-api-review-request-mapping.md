# 001 Legacy API to ReviewRequest.v1 Mapping

Backlog 001 introduces a Rust artifact core without moving the legacy Elixir API
or GitHub Action client. This note maps the existing API-dispatch shape to the
new source-agnostic request contract so adapter work can stay thin.

## Boundary

Legacy callers may continue to submit through `dispatch.sh` and the Elixir API.
The Rust core starts at an already-acquired `ReviewRequest.v1` plus
`ReviewConfig.v1` and returns a `ReviewRunArtifact.v1`.

No GitHub posting, polling, queueing, auth, or hosted-service behavior belongs
inside `cerberus-core`.

## Field Mapping

| Legacy surface | ReviewRequest.v1 field | Notes |
| --- | --- | --- |
| `repository` / `GITHUB_REPOSITORY` | `source.repository` when `source.kind = "github_pr"` | Optional for `git_range`; required for GitHub PR fixtures. |
| `pull_request.number` / `pr_number` | `source.pr_number` | Caller-owned acquisition concern; core only sees the number. |
| `base_ref` | `source.base_ref` and `change.base_ref` | Source fields identify acquisition; change fields document reviewed content. |
| `head_ref` | `source.head_ref` and `change.head_ref` | Same split as `base_ref`. |
| `head_sha` | `source.head_sha` and `change.head_sha` | Optional until adapters can always provide it. |
| PR title | `change.title` | Required because artifacts and rendered summaries need a stable subject. |
| PR body / issue context | `change.description`, `context.summary`, `context.acceptance`, `context.linked_artifacts` | Semantic enrichment belongs to reviewer agents later, not regex glue. |
| Unified diff file/body | `change.diff` | Required for the offline oracle. |
| changed files | `change.files[]` | Exact syntax/metadata, not semantic judgment. |
| Action run metadata | `caller.name`, `caller.run_id`, `context.metadata` | Keeps source identity out of the core engine. |
| model input | `ReviewConfig.v1.reviewers[].model` | The request describes the change; reviewer selection belongs to config. |
| timeout/degraded state | `ReviewerArtifact.v1.status`, `ReviewRunArtifact.v1.degraded`, `reserves[]` | Produced by execution, not request acquisition. |
| override approvals | `policy.override_approval` and `ReviewRunArtifact.v1.override_applied` | The core records the policy and applied override; callers decide posting. |

## Adapter Rules

- Build `ReviewRequest.v1` from exact source metadata and diff content.
- Fetch semantic context through reviewer agents or later adapter APIs, not
  keyword or regex inference in shell glue.
- Preserve caller ownership: GitHub review posting stays outside
  `cerberus-core`; Bitterblossom and Olympus adapters must not import each
  other.
- Store and replay `ReviewRunArtifact.v1` as the review receipt. Rendered
  Markdown and inline-comment candidates are projections of that artifact.
