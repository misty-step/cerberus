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
  --receipt-bundle target/cerberus/receipts/fixture.json \
  --producer-manifest target/cerberus/producer-manifest.json

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
  --gh-token-file /path/to/github-app-installation-token \
  --post

# Agent-native: review the current branch against a base in one command,
# review printed to stdout, no GitHub and no token.
cerberus review-diff --base origin/master --fail-on fail
```

## Agent-native handoff

The primary way to call Cerberus from another agent (or CI, or a script) is to
spawn it on a local diff, read the review off **stdout**, and branch on the
**exit code** — no GitHub, no token, no intermediate request file:

```sh
cerberus review-diff --base origin/master --head HEAD \
  --harness opencode --model openrouter/z-ai/glm-5.2 \
  --allow-env OPENROUTER_API_KEY \
  --fail-on fail
```

- **stdout** carries only the review (rendered Markdown; pass `--json` for the
  raw `ReviewArtifact.v1`). Logs and errors go to stderr.
- The **exit code** is the gate a calling agent branches on:

  | Exit | Meaning | When |
  |------|---------|------|
  | `0`  | clean — proceed | a valid review was produced and the verdict is below `--fail-on` (or `--fail-on none`, the default) |
  | `1`  | blocking — read the review | a valid review was produced and the verdict is at or above the threshold (`--fail-on fail` ⇒ `FAIL`; `--fail-on warn` ⇒ `WARN`/`FAIL`) |
  | `2`  | Cerberus error — no review | the harness failed, the artifact did not validate, the invocation was invalid, or no review could be produced |

`--fail-on` is also available on `cerberus review`. Without it, exit status is
unchanged (`0` on a valid artifact regardless of verdict, `2` on error), so
existing callers are unaffected. Use `--out`/`--markdown` to also persist the
artifact and Markdown to files while still printing to stdout.

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
Posting refuses ambient/keyring `gh` auth: pass exactly one explicit token
source, either `--gh-token-file <path>` or `--gh-token-env <VAR>`. If the token
is a GitHub App installation token, Cerberus posts as that app identity; token
minting remains the caller/CI boundary.

## MCP

Cerberus also ships a small stdio MCP server for agents that prefer tool calls
over shelling out:

```sh
cerberus mcp
```

The MCP surface is intent-shaped rather than a CLI mirror:

- `review_git_range` reviews a committed local `base...head` range and returns
  the rendered review plus verdict metadata.
- `render_review_artifact` renders a saved `ReviewArtifact.v1` to Markdown.
- `validate_review_artifact` validates a saved artifact against its
  `ReviewRequest.v1`.

For local implementation work, `cerberus review-diff --base <ref> --fail-on
fail` remains the lowest-friction handoff. Use MCP when the calling agent has a
native MCP client and benefits from tool schemas/results.

`ReviewReceiptBundle.v1` is the upstream evaluation handoff. It records the
request digest, artifact digest, harness, model and usage when available,
latency, capability tier, artifact/transcript URIs, and validation outcome
without embedding prompt files, request files, secret names, or transcript
excerpts. Daedalus or another lab can score those bundles without Cerberus
owning model or harness evaluation.

## Crucible producer handoff

Crucible owns grading, intervals, adjudication, and Harbor export. Cerberus's
producer side is the two-step request/review path:

```sh
cerberus request git-range --repo-path /path/to/workspace \
  --base <base-sha> --head <head-sha> \
  --out target/cerberus/crucible-producer/request.json

cerberus review --request target/cerberus/crucible-producer/request.json \
  --harness opencode \
  --out target/cerberus/crucible-producer/artifact.json \
  --execution-plan target/cerberus/crucible-producer/execution_plan.json \
  --transcript target/cerberus/crucible-producer/transcript.txt \
  --receipt-bundle target/cerberus/crucible-producer/receipt-bundle.json \
  --producer-manifest target/cerberus/crucible-producer/producer-manifest.json
```

`producer-manifest.json` is metadata only: it points Crucible at the validated
`ReviewArtifact.v1` `findings` array, records the redacted receipt bundle digest
and validation state, and explicitly says the scorer owner is `crucible` with no
score included. The repo gate writes the same packet under
`target/cerberus/crucible-producer/` and checks that the artifact is gradeable
by Crucible's adapter contract.

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
