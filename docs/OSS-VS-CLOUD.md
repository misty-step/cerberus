# OSS (BYOK) vs Cerberus Cloud

Cerberus is an open core project.

## Summary

- **Cerberus OSS (this repo)**: GitHub Actions. You bring your own model API key. Cerberus runs entirely inside your workflow runner.
- **Cerberus Cloud (planned)**: GitHub App. Managed keys + quotas + org controls. Posts the same council UX back to GitHub.

Source of truth: `docs/adr/002-oss-core-and-cerberus-cloud.md`.

## Feature Matrix

| Capability | OSS (BYOK Action) | Cloud (GitHub App) |
|---|---:|---:|
| Install surface | Workflow YAML + secret | App install (zero YAML) |
| Fork PR review | No (secrets unavailable) | Yes (no repo secrets needed) |
| Model keys | Your key | Managed by Cloud |
| Metering | Your provider limits | Enforced quotas + budgets |
| Org policy | Via repo workflow/config | Central org controls |
| Primary UX | PR comments + PR review + checks | Same |

## Data Flow (High Level)

- OSS: code/diffs flow to your configured model provider (via your API key). Cerberus does not run a server.
- Cloud: code/diffs flow to Cerberus Cloud runtime and then to its model providers. Cerberus becomes an additional processor.

