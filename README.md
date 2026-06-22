# Cerberus

Cerberus is a context-adaptive AI code review runner. It accepts a
source-agnostic `ReviewRequest.v1`, gives one master reviewer the available
context through `ReviewKernel`, validates the returned `ReviewArtifact.v1`, and
renders or posts the result for callers such as local scripts and GitHub pull
requests.

There are no predefined reviewer subagents. The Cerberus master may launch
ephemeral substrate subagents at runtime when the diff and context call for
them. Rust owns the contracts, capability boundaries, receipts, validation, and
rendering.

OpenCode is the preferred production-oriented substrate because its
server/session-first shape fits durable automated review better than a
terminal-first wrapper. OMP remains supported as a local power-user fallback.
OpenCode, OMP, and fixture-specific options live behind `ReviewSubstrate`
adapter configs; callers pass a `RunPolicy` into `ReviewKernel::review`.

See [VISION.md](VISION.md) for project direction and what excellent looks like,
and [spec.md](spec.md) for the locked MVP contract.

## Verify

```sh
./scripts/verify.sh
```

The verification script formats, lints, tests, checks the default harness
surface, runs deterministic fixture reviews, smokes both the OpenCode and OMP
harness paths through local fake binaries, exercises base+head context and
local runtime probes, and runs `review-pr` through a fake `gh` adapter.
Evidence is written to `target/cerberus/`, including execution plans,
transcripts, artifacts, rendered Markdown, post plans, post results, context
tier receipts, evaluation receipt bundles, and fake GitHub API transcripts.

## CLI

```sh
cerberus request git-range --base origin/master --head HEAD \
  --out target/cerberus/request.json

cerberus request git-range --base origin/master --head HEAD \
  --local-runtime-command env \
  --allow-local-runtime \
  --allow-env CERBERUS_RUNTIME_FLAG \
  --out target/cerberus/runtime-request.json

cerberus request pr --number 123 --out target/cerberus/request.json

cerberus review --request fixtures/requests/diff-only.json \
  --harness fixture \
  --fixture-output fixtures/harness/valid-review.txt \
  --out target/cerberus/artifact.json \
  --markdown target/cerberus/review.md \
  --execution-plan target/cerberus/execution_plan.json \
  --receipt-bundle target/cerberus/receipts/fixture.json

cerberus render --artifact target/cerberus/artifact.json \
  --markdown target/cerberus/review-rendered.md

cerberus review-pr --number 123 --repo owner/name \
  --harness opencode \
  --out-dir target/cerberus/review-pr \
  --dry-run

cerberus review-pr --number 123 --repo owner/name \
  --harness opencode \
  --out-dir target/cerberus/review-pr \
  --summary-target check-run \
  --post
```

Git range requests include disposable base and head worktree capability from
the supplied refs. PR requests may include `--head-workspace` and
`--base-workspace` when the caller has safe local checkouts at the PR head and
base SHAs. Local runtime probes run only when both `--local-runtime-command`
and `--allow-local-runtime` are present; probe env is restricted to
`--allow-env` plus a trusted `PATH`, and transcripts are captured in the review
transcript.

The fixture substrate is for deterministic verification. The production path is
the OpenCode substrate using the `build` agent profile by default against
disposable review worktrees; OMP is a local fallback.

`review-pr` is orchestration over acquisition, review, rendering, and GitHub
projection. It writes `request.json`, `artifact.json`, `review.md`,
`execution_plan.json`, `transcript.txt`, `receipt-bundle.json`, and
`post-plan.json` under `--out-dir`. `--dry-run` reads existing GitHub
comments/checks through `gh api` and prints the exact create/update plan
without writing. `--post` applies that plan and writes `post-result.json`.

`ReviewReceiptBundle.v1` is the upstream evaluation handoff. It records the
request digest, artifact digest, harness, model and usage when available,
latency, capability tier, artifact/transcript URIs, and validation outcome
without embedding prompt files, request files, secret names, or transcript
excerpts. Daedalus or another lab can score those bundles without Cerberus
owning model or harness evaluation.

GitHub Checks writes require a token with Checks write access, usually a GitHub
App or fine-grained token. Classic user tokens commonly cannot create check
runs. Use `--summary-target status` when commit statuses are the available
credential boundary; status posting is append-only by GitHub design, but the
latest `Cerberus Review` context is what branch protection reads. Review
summary and inline comments use per-head-SHA markers so repeated runs update
prior Cerberus output instead of duplicating it.

For an operator-gated live smoke, set `CERBERUS_LIVE_REVIEW_PR=1`,
`CERBERUS_LIVE_REVIEW_REPO=owner/name`, and
`CERBERUS_LIVE_REVIEW_NUMBER=<pull request number>` before running
`./scripts/verify.sh`. The live smoke defaults to `--dry-run` and
`--summary-target status`; set `CERBERUS_LIVE_REVIEW_POST=1` only when the
target PR is intentionally allowed to receive Cerberus output.
