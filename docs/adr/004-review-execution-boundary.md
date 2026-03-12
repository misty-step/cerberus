# ADR 004: Review Execution Boundary via Review-Run Contract

- Status: Accepted
- Date: 2026-03-12
- Deciders: Cerberus maintainers
- Related: #323, #324, #325, #326, #328

## Context

Cerberus currently ships as a GitHub Action, but the engine path still consumes GitHub-shaped bootstrap data directly:
- `GH_DIFF_FILE`
- `GH_PR_CONTEXT`
- `GH_TOKEN`
- `CERBERUS_REPO`
- `CERBERUS_PR_NUMBER`

That leaks GitHub Actions semantics into engine code and makes self-hosted or future Cloud orchestration harder to support without re-implementing the runner.

At the same time, GitHub CLI transport logic had drifted across multiple review/reporting scripts, which made the platform boundary shallow and harder to reason about.

## Decision

1. Introduce a provider-agnostic **review-run contract** as the engine input for review execution.
2. Keep the GitHub Action as the default OSS distribution, but have it write the contract before invoking the engine runner.
3. Keep GitHub-specific `gh` transport and retry/permission behavior behind `scripts/lib/github_platform.py`.
4. Preserve current public behavior for the GitHub Action path while making the internal boundary explicit.

## Boundary

```mermaid
graph TD
  A["GitHub Action / workflow"] --> B["GitHub bootstrap"]
  B --> C["review_run_contract.json"]
  C --> D["Engine runner (run-reviewer.py)"]
  D --> E["Prompt rendering + runtime facade"]
  D --> F["github_platform (only for GitHub-specific helpers)"]
  E --> G["Pi runtime"]
```

- **Inside the engine boundary**
  - review-run contract loading
  - prompt rendering
  - runtime execution
  - parse handoff

- **Inside the GitHub platform boundary**
  - `gh` transport
  - retry/permission classification for GitHub calls
  - review/report helper calls that talk to GitHub APIs

- **Outside scope for this boundary**
  - Cloud billing, worker leasing, quotas, or Sprite orchestration
  - verdict schema redesign
  - prompt-policy redesign

## Consequences

### Positive

- Engine code now has a stable input shape that is not tied to raw GitHub env names.
- GitHub-specific logic has one clearer home.
- Future self-hosted or alternate orchestrators can target the contract instead of reusing Action-only glue.
- Tests and docs can guard against accidental recoupling.

### Negative

- The GitHub Action path now has one more artifact to manage.
- Legacy env fallbacks must remain for compatibility during migration.

## Alternatives Considered

1. Keep raw `GH_*` env bootstrap in engine code.
   - Rejected: preserves hidden GitHub coupling.
2. Rewrite the entire workflow bootstrap path in one PR.
   - Rejected: too much risk for one lane.
3. Build a Cloud-specific execution layer first.
   - Rejected: violates OSS boundary goals and expands scope unnecessarily.
