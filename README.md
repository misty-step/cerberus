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
reviewer plans, transcripts, artifacts, rendered Markdown, post plans, post
results, context tier receipts, evaluation receipt bundles, and fake GitHub API
transcripts.

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
  --gh-token-env CERBERUS_GH_TOKEN \
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
`execution_plan.json`, `reviewer_plan.json`, `transcript.txt`,
`receipt-bundle.json`, and `post-plan.json` under `--out-dir`. `--dry-run` reads existing GitHub
comments/checks through `gh api` and prints the exact create/update plan
without writing. `--post` applies that plan and writes `post-result.json`.
Because dry-run still reads GitHub state, `review-pr` refuses ambient/keyring
`gh` auth for both reads and writes: pass exactly one explicit token source,
either `--gh-token-file <path>` or `--gh-token-env <VAR>`. If the token is a
GitHub App installation token, Cerberus posts as that app identity; token
minting remains the caller/CI boundary.

## Untrusted-PR review (scoped keys + container isolation)

**The default review path is not safe against an untrusted diff.** A plain
`--allow-env OPENROUTER_API_KEY` review gives the substrate (which has shell
and webfetch access) your real, long-lived OpenRouter key and an unrestricted
network — a prompt-injected PR can exfiltrate both. Only turn on the two
flags below, together, before pointing Cerberus at a PR you do not trust.

**M1 — scoped, capped, revocable credentials** (`--openrouter-scoped-key`).
Instead of forwarding your real key, Cerberus mints a brand-new OpenRouter key
for this one review, hard-capped in USD, and revokes it (or a sweeper does, if
the process crashes) when the review ends. If the diff steals it, the thief
gets a key worth at most the cap, already dead by the time they'd replay it.

- `--openrouter-scoped-key` — turn minting on.
- `--openrouter-provisioning-key-file <path>` / `--openrouter-provisioning-key-env <VAR>`
  — exactly one, the source of your OpenRouter *provisioning* (management) key
  used to mint the scoped key. Never the review key itself.
- `--openrouter-key-limit-usd <amount>` — the USD cap on the minted key
  (default `5`; must be a positive number).
- `--openrouter-orphan-sweep-seconds <seconds>` — age past which a leftover
  key from a crashed prior run is revoked before minting a fresh one (default
  `1800`).

**M2 — container isolation with a model-only egress exception**
(`--harness container-opencode`). The substrate runs inside a locked-down
Docker container: read-only root filesystem, no capabilities, non-root user,
and network access to exactly one `host:port` — the model API — via a
CONNECT-only proxy. Every other host, including for DNS resolution, is
unreachable from inside the sandbox. The container never sees your real
checkout path; it works from a disposable `.git`-less copy of the diff.

- `--harness container-opencode` — select the isolated substrate.
- `--container-binary <path>` — host path to the substrate executable,
  bind-mounted read-only and exec'd inside the container. Required.
- `--container-image <image>` — base image the substrate runs inside (default
  `debian:bookworm-slim`). No image is built; a stock image is used as-is.
- `--container-egress-allow-host <host:port>` — the one reachable destination
  (default `openrouter.ai:443`).
- `--container-host-root <path>` — parent directory for the disposable per-run
  container root; defaults to the OS temp dir. Point this somewhere your
  Docker daemon can actually see if it runs inside a VM with a narrow mount
  allowlist (colima's default mounts only `$HOME`, not the OS temp dir).

Combined:

```sh
cerberus review-pr --number 123 --repo owner/name \
  --gh-token-env CERBERUS_GH_TOKEN \
  --harness container-opencode \
  --container-binary /usr/local/bin/opencode \
  --openrouter-scoped-key \
  --openrouter-provisioning-key-env OPENROUTER_MANAGEMENT_KEY \
  --openrouter-key-limit-usd 2 \
  --dry-run
```

Both milestones are live-verified, production-enabled (backlog 013 M1/M2,
merged and evidence-recorded 2026-07-01). M3 (an optional further hardening
pass) is not started and not scheduled.

## Review doctrine

`src/review_doctrine.md` is the shared vocabulary the master reviewer draws on
for every review — Fowler-smell terms, the "plausible-but-wrong" failure mode
of model-written code, a structural-ambition bar, and a mandatory dimension:
*heuristic where a model belongs, and model where deterministic code belongs*
(backlog 023) — every review must ask both whether a change quietly replaced
model-native judgment with a brittle heuristic, and whether it added a model
call where deterministic, oracle-checkable code should own the behavior
instead. `ReviewReceiptBundle.v1` records a `review_doctrine_digest` (a hash
of that file) so any receipt can show which doctrine version — and therefore
which mandatory dimensions — governed a given run.

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
excerpts. Threshold or another lab can score those bundles without Cerberus
owning model or harness evaluation.

`ReviewerPlanReceipt.v1` is the orchestration sidecar. The current path records
diff understanding, available and skipped context, the single-master lane
decision, and the synthesis/validation contract. Dynamic child lanes will extend
that receipt rather than bypassing `ReviewArtifact.v1`.

Child lanes are launched through a `ReviewerLaneSubstrate` interface over
`ReviewerLanePlan` data. Roles are plan fields, not built-in Rust personas; a
lane substrate receives scoped objective/context/budget/stop-condition data and
returns a `ReviewerLaneReceipt.v1`.

The master prompt treats those lane receipts as evidence to synthesize into the
single `ReviewArtifact.v1`. Child-lane claims must still satisfy the artifact's
anchor, citation, context-capability, and validation rules.

## Crucible producer handoff

Crucible owns grading, intervals, adjudication, and Harbor export. Cerberus's
producer side is the two-step request/review path:

```sh
cerberus request git-range --repo-path /path/to/workspace \
  --base <base-sha> --head <head-sha> \
  --out target/cerberus/crucible-producer/request.json

cerberus review --request target/cerberus/crucible-producer/request.json \
  --harness opencode \
  --model openrouter/z-ai/glm-5.2 \
  --allow-env OPENROUTER_API_KEY \
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

### Artifact schema contract

`schemas/review-artifact.schema.json` is a committed JSON Schema for
`cerberus.review_artifact.v1`, and `schemas/review-artifact.example.json` is a
canonical fixture that validates against it. Both are generated from the live
`ReviewArtifact` struct and its serializer, never hand-maintained:

```sh
cargo run --example gen_review_artifact_schema > schemas/review-artifact.schema.json
cargo run --example gen_review_artifact_fixture > schemas/review-artifact.example.json
```

`tests/review_artifact_schema.rs` fails if either committed file drifts from
what the live code produces, so an incompatible `schema.rs` change forces a
conscious regeneration and review of the diff before it can merge. This
fixture is the documented regeneration source for Crucible's own mirror
(`crucible-core/tests/fixtures/cerberus-artifact.json`, which mirrors the
struct shape by hand in `crucible-core/src/artifact.rs`) — when this fixture
changes, regenerate Crucible's copy from it rather than letting the two drift
independently.

GitHub Checks writes require a token with Checks write access, usually a GitHub
App or fine-grained token. Classic user tokens commonly cannot create check
runs. Use `--summary-target status` when commit statuses are the available
credential boundary; status posting is append-only by GitHub design, but the
latest `Cerberus Review` context is what branch protection reads. Review
summary and inline comments use per-head-SHA markers so repeated runs update
prior Cerberus output instead of duplicating it.

For an operator-gated live smoke, set `CERBERUS_LIVE_REVIEW_PR=1`,
`CERBERUS_LIVE_REVIEW_REPO=owner/name`, and
`CERBERUS_LIVE_REVIEW_NUMBER=<pull request number>` plus exactly one of
`CERBERUS_LIVE_REVIEW_GH_TOKEN_FILE` or `CERBERUS_LIVE_REVIEW_GH_TOKEN_ENV`
before running `./scripts/verify.sh`. The live smoke defaults to `--dry-run`
and `--summary-target status`; set `CERBERUS_LIVE_REVIEW_POST=1` only when the
target PR is intentionally allowed to receive Cerberus output.
