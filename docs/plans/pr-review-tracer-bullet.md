# Context Packet: PR Review Tracer Bullet

## Goal

Let Cerberus review a pull request end to end from a generated
`ReviewRequest.v1`: acquire PR or git-range context, run the existing harness,
and render a durable review artifact.

## Non-Goals

- No GitHub inline posting in this slice.
- No webhook, queue, recurring worker, or Bitterblossom handoff yet.
- No model/harness evaluation matrix.
- No container sandbox beyond the current local process harness.

## Constraints

- Keep Cerberus as a thin Rust review runner, not a GitHub platform.
- Preserve the single predefined master reviewer rule.
- Keep OpenCode as the default substrate and OMP as fallback.
- Do not pass prompt or diff material through argv.
- Do not leak ambient credentials into child review processes unless policy
  explicitly allows an env var.

## Repo Anchors

- `src/main.rs`: CLI shape and command dispatch.
- `src/schema.rs`: `ReviewRequest.v1` and `ReviewArtifact.v1`.
- `src/harness.rs`: review substrate execution and receipt capture.
- `src/validation.rs`: request and artifact validation.
- `scripts/verify.sh`: repository proof loop.
- `fixtures/requests/diff-only.json`: request exemplar.
- `docs/adr/0002-opencode-as-default-review-substrate.md`: substrate decision.

## Alternatives

| Alternative | Why It Fails | Verdict |
|---|---|---|
| Hand-author request JSON for every PR | Proves the schema but not product ergonomics; too brittle for self-review. | Reject |
| Build GitHub posting first | Turns the tracer into a platform adapter before the review request loop is proven. | Reject |
| Add a `request git-range` producer only | Fastest local proof, but does not prove PR acquisition. | Partial |
| Add `request pr` plus `request git-range` | Covers GitHub PR review and local self-review while staying outside posting/webhooks. | Choose |

## Design

Add a new CLI producer:

```text
cerberus request git-range --base <ref> --head <ref> --out <request.json>
cerberus request pr --number <n> --out <request.json>
```

`git-range` uses local `git diff --no-ext-diff --binary --find-renames` and
`git diff --numstat` to populate the change. `pr` uses `gh pr view --json` for
metadata and `gh pr diff --patch/--name-only` for the patch. Both write
`ReviewRequest.v1`; they do not run the review themselves.

The existing `review` and `render` commands remain the execution path:

```text
cerberus request pr --number <n> --out target/cerberus/pr/request.json
cerberus review --request target/cerberus/pr/request.json --harness opencode ...
cerberus render --artifact target/cerberus/pr/artifact.json --markdown ...
```

## Oracle

Executable definition of done:

```sh
./scripts/verify.sh
cargo run --locked -- request git-range --base origin/master --head HEAD \
  --out target/cerberus/self-review-request.json
cargo run --locked -- review --request target/cerberus/self-review-request.json \
  --harness fixture --fixture-output fixtures/harness/pass-review.txt \
  --out target/cerberus/self-review-artifact.json \
  --markdown target/cerberus/self-review.md
```

The first command proves the repo gate. The second proves request generation
from the live branch. The third proves the generated request can traverse the
existing review and render path. A real OpenCode run is an operator smoke once
the request producer exists and a model/env allowlist is selected.

Verification system:

- Claim: Cerberus can acquire PR/git-range context and feed it into the review
  harness as a valid `ReviewRequest.v1`.
- Falsifier: generated requests fail validation, contain wrong context
  capability claims, lose changed-file anchors, or cannot be reviewed/rendered.
- Driver: `./scripts/verify.sh` plus the `request git-range` and fixture review
  smoke above.
- Grader: command exit codes, nonempty request/artifact/markdown files, and
  validation performed by `review`.
- Evidence packet: `target/cerberus/*request*.json`,
  `target/cerberus/*artifact*.json`, `target/cerberus/*review*.md`.
- Cadence: pre-merge for this tracer; later CI once the interface stabilizes.
- Gaps / waiver: real OpenCode model quality and GitHub posting are explicitly
  out of this tracer bullet.

## Premise Source

- `sha256:61c175ddccb843175819f972f2b3399bb09ccbb0bade5af8d4849091c153b13a spec.md`
- `sha256:a037ad81a79f6d9040c9cbdf4459c452d2f4b70334aa3933914c58d228a7f285 docs/adr/0002-opencode-as-default-review-substrate.md`
- `sha256:0c77b067096de3564b7ff5f861824fff4c2e5c86026790b7e9fcac2881618dd1 /Users/phaedrus/.codex/attachments/2f60e9ed-7aba-45eb-8a31-96eaeda536e7/pasted-text.txt`

## HTML Plan

`docs/plans/pr-review-tracer-bullet.html`

## Risks + Rollout

- Risk: `gh` output shape changes. Mitigation: use documented `--json` fields
  and smoke the local command in `scripts/verify.sh`.
- Risk: generated file status parsing is incomplete. Mitigation: support the
  common modified/added/removed/renamed statuses and fail loudly on ambiguous
  records.
- Risk: users confuse request generation with posting. Mitigation: keep the
  producer verb separate from `review` and leave posting out of scope.
- Rollout: merge as a manual local CLI path first, then add `cerberus review-pr`
  or GitHub posting only after self-review produces useful artifacts.
