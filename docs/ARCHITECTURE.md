# Cerberus Architecture

Cerberus now has one public review path:

1. a thin GitHub Action client at repo root
2. the legacy Elixir compatibility engine in `cerberus-elixir/`

## Resurrection Target

The current path above is the legacy compatibility surface. ADR 006 changes the
long-term architecture target to a Rust review-artifact core:

```text
ReviewRequest.v1 + ReviewConfig.v1 + ReviewPolicy.v1
    -> Cerberus Rust core
    -> ReviewRunArtifact.v1
```

The GitHub Action, hosted API, and dispatch/poll flow may wrap that core as
adapters, but they do not define the core boundary. Bitterblossom and Olympus
remain independent callers through the same contract; neither caller should know
about the other.

Backlog 005 tracks every legacy surface in
`docs/shaping/legacy-surface-retirement.md` and its machine-checked JSON
inventory. That inventory is the source of truth for whether a surface is kept,
ported, deleted, or archived.

ThinkTank is historical donor material for review execution, not a production
runtime dependency. Frozen ThinkTank review runs may be imported by
`crates/cerberus-adapter` for migration and eval replay, but `cerberus-core`
owns the review request, configuration, and artifact semantics directly.

`crates/cerberus-adapter` is the consumer-side SDK and fixture home for that
contract. It may provide request builders, caller receipt examples, and artifact
projections, but it must not move caller-owned runtime concerns into
`cerberus-core`. It also owns one-way historical importers for donor systems
such as ThinkTank, so old review evidence can be replayed without changing the
core engine boundary.

`cerberus-core` reviewer execution now crosses the `ReviewHarness` boundary:
configured reviewers plus a `ReviewRequest.v1` produce `ReviewerArtifact.v1`
values, then core validates reviewer identity, finding citation coverage, and
verdict consistency before aggregating. The default `DeterministicHarness` keeps
local fixture behavior stable; live Pi, Goose, OpenCode, OMP, Sprites, or
provider adapters attach behind this boundary.

Peer harness command profiles are validated data before they are live execution.
`PeerHarnessCommandProfiles.v3` records the future protocol runner command and
the underlying peer CLI template; raw peer CLIs do not define the Cerberus
input/output contract.

`cerberus-peer-harness` is the Rust protocol command named by those profiles.
It currently proves file handoff and artifact validation offline by emitting a
degraded `SKIP` artifact with exact request coverage. It can also render a
deterministic prompt and parse exact marked local transcript fixtures into
reviewer artifacts. Fixture-backed live peer invocation now runs behind
`CERBERUS_PEER_HARNESS_LIVE=1`; provider-backed Pi/Goose/OpenCode/OMP profiles
now use private prompt-file transport and remain blocked until provider-budget
acknowledgement and required credentials are present.

`cerberus-cli eval-harness --execution-mode live-peer` drives the same peer
protocol runner for harness/model evaluation cells. `cerberus-core` owns eval
artifact validation and scoring; the CLI owns live process orchestration and
writes per-cell input, reviewer artifact, transcript, and execution-plan
evidence. Offline eval cells remain warning-only; local live fixture cells may
pass, while provider-backed live cells remain unavailable until budget and
credentials are explicitly supplied.

`cerberus-cli review-local` is the Rust local diff replay path. It reads a
git-style diff file, builds a `ReviewRequest.v1` with `LocalDiff` source, runs
the Rust review core, and writes the same request, artifact, and Markdown
surfaces as fixture review. It does not shell out to Git, infer semantic
reviewer routing from the diff, or replace hosted API compatibility. Both
fixture review and local replay can use `--config-packet` to execute the
embedded `ReviewConfig.v1` from a validated `ReviewerConfigPacket.v1`; that is a
sandbox execution source, not default promotion.

`cerberus-cli github-action-request` is the first Rust GitHub Action adapter
slice. It reads a checked `pull_request` event payload and unified diff,
returns fork/draft skip decisions before diff file IO, treats missing fork head
repo metadata as a skip, and writes `ReviewRequest.v1` for same-repo PRs. It
does not call GitHub, call the hosted Cerberus API, poll for verdicts, write
GitHub Actions outputs, or own the full action runtime.

`cerberus-cli hosted-api-dispatch-fixture` is the second Rust GitHub Action
adapter slice. It consumes checked hosted API POST and poll transcripts, then
writes the simulated action decision: outcome, exit code, review-id, verdict,
GitHub output map, elapsed poll budget, and optional verdict JSON. It is a pure
state machine for fixture parity; it does not make network calls, write the
real `$GITHUB_OUTPUT` file, or own the full action runtime. Its elapsed seconds
follow the legacy shell client's sleep-before-poll accounting. It intentionally
hardens one legacy edge case by treating an accepted dispatch response without
`review_id` as a failed dispatch instead of polling an empty review URL.

`cerberus-cli github-action-dispatch` is the active Rust GitHub Action adapter
slice. It reads the action environment contract, skips fork and draft PRs before
requiring hosted secrets, sends the hosted API POST with a Rust HTTP client,
polls the hosted review, appends `review-id` and `verdict` to the configured
GitHub output file, writes verdict JSON under `RUNNER_TEMP` when available, and
exits according to the hosted dispatch decision. `action.yml` invokes this Rust
command through Cargo from the checked-out action path. The former root
`dispatch.sh` rollback file was archived after Rust entrypoint parity.

## Request Flow

```text
pull_request event
    │
    ▼
action.yml
    │
    ▼
cerberus-cli github-action-dispatch
    │
    ├── POST /api/reviews
    ├── poll GET /api/reviews/:id
    └── emit verdict output

cerberus-elixir/
    ├── accepts review request
    ├── runs reviewer agents
    ├── aggregates verdict
    └── persists run state
```

## Design Rules

- Keep the GitHub Action client thin.
- Keep legacy review orchestration in Elixir until Rust parity is fixture-backed.
- Keep product data in `defaults/` and `pi/agents/`.
- Delete or archive compatibility layers only through the retirement inventory.

## Active Modules

### Root Action

- `action.yml`
- `templates/consumer-workflow-reusable.yml`
- `cerberus-cli init`
- `cerberus-cli init-workflow`

Responsibilities:

- launch the Rust dispatcher from the checked-out action workspace
- validate basic PR context
- dispatch to the API
- poll until completion
- expose workflow outputs
- keep the public input/output contract stable
- scaffold the consumer workflow, prompt for `CERBERUS_API_KEY` on interactive
  Unix TTYs, and set the repository secret through Rust

Rollback surface:

- Restore the archived shell dispatcher from Git history only if Rust action
  dispatch parity regresses and the retirement inventory rollback path is
  followed.
- Restore the archived npm scaffolder files from Git history only if a real npm
  package compatibility requirement appears.

### Rust Adapter SDK

Lives in `crates/cerberus-adapter/`.

Responsibilities:

- build and validate caller-shaped `ReviewRequest.v1` values
- build GitHub Actions `pull_request` event fixtures into `ReviewRequest.v1`
  without network, token, or hosted API behavior
- model hosted API dispatch and polling decisions from checked transcripts,
  including fail-on-verdict, timeout, poll errors, hosted failure, malformed
  dispatch responses, and GitHub output values
- run hosted dispatch loops through a supplied transport so fixture and real
  HTTP callers share one decision path
- prove the local fixture contract shape for Bitterblossom and Olympus without
  cross-caller references
- project `ReviewRunArtifact.v1` into caller-owned receipt/posting shapes
- guard fixture text against cross-caller references
- import frozen historical donor artifacts into public Cerberus schemas
- provide command harness adapters that launch external reviewer processes
  behind `ReviewHarness`
- validate peer harness command profiles for Pi, Goose, OpenCode, and OMP

Non-responsibilities:

- Bitterblossom task queues, retries, budgets, or run ledgers
- Olympus Argus activation gates, stale-head suppression, marker dedupe, caps,
  or GitHub posting
- live acquisition from either caller repository
- concrete hosted API HTTP client selection or GitHub Actions environment IO
- production review execution through the ThinkTank CLI
- reviewer artifact acceptance, aggregation, or degradation semantics

### Rust Harness Boundary

Lives in `crates/cerberus-core/`.

Responsibilities:

- accept validated reviewer configs and review requests
- run reviewer execution through `ReviewHarness`
- convert harness failures or invalid artifacts into degraded reviewer
  artifacts
- keep aggregation independent from GitHub, shell commands, provider APIs, and
  caller runtimes

Non-responsibilities:

- spawning live peer harness CLIs
- provider authentication
- hosted API dispatch
- caller-owned retry, queue, budget, or posting policy

### Rust Command Harness Adapter

Lives in `crates/cerberus-adapter/`.

Responsibilities:

- serialize a reviewer/request input envelope
- launch a configured command with explicit `--input` and `--output` paths
- map non-zero exits and timeouts into `HarnessRuntimeError`
- return command-emitted `ReviewerArtifact.v1` values to core validation

Non-responsibilities:

- Pi, Goose, OpenCode, or OMP prompt construction
- provider credentials or paid model calls
- artifact aggregation or acceptance policy
- hosted API dispatch

### Peer Harness Profiles

Live as schema and fixtures in `cerberus-schema` and `fixtures/harnesses/`.

Responsibilities:

- describe CommandHarness protocol runner commands as data
- record the underlying peer CLI invocation templates for Pi, Goose, OpenCode,
  and OMP
- declare required environment variables, timeouts, output contract, and
  unsupported containment boundaries

Non-responsibilities:

- executing paid provider calls
- ranking model or harness quality
- replacing the eval matrix

### Peer Harness Protocol Runner

Lives as `cerberus-peer-harness` in `crates/cerberus-cli/`.

Responsibilities:

- validate peer command profile packets
- select the requested harness profile
- read `CommandHarnessInput`
- write offline degraded `ReviewerArtifact.v1` files with exact request
  coverage
- write deterministic peer review prompts to local files
- write schema-valid execution plans that expose the exact peer command,
  resolved args, environment status, timeout, output contract, and transcript
  markers without embedding secret values or the rendered prompt
- invoke peer commands under `CERBERUS_PEER_HARNESS_LIVE=1` through the
  bounded Rust adapter subprocess primitive
- capture live stdout transcripts and parse exact marked reviewer artifact JSON
- parse local transcripts that contain exactly one marked reviewer artifact JSON
  block
- validate parsed artifacts against the core reviewer/request acceptance rule
- fail closed before provider-backed execution unless the profile budget
  acknowledgement is explicit and prompt transport avoids argv
- write private prompt files for `prompt_file` profiles and delete them after
  live peer execution

Non-responsibilities:

- execution-plan scheduling or retry policy
- free-form transcript interpretation
- model budget or quality evaluation

### Harness and Model Evaluation

Lives in `crates/cerberus-core/src/harness_eval.rs`,
`cerberus-cli eval-harness`, and `fixtures/evals/`.

Responsibilities:

- grade reviewer artifacts against eval tasks in `cerberus-core`
- emit `HarnessModelEvaluationReport.v1`
- scan stale model IDs in configured source paths
- run offline contract cells without marking them production-ready
- run local live peer cells through `cerberus-peer-harness` when explicitly
  requested
- write inspectable input, artifact, transcript, and execution-plan evidence
  for live peer cells
- derive sandbox-only `ReviewerConfigPacket.v1` candidates from fully passing
  live eval groups
- let review commands execute validated packet configs with `--config-packet`
  before any caller depends on a measured config

Non-responsibilities:

- promoting reviewer defaults without a reviewed report
- spending provider budget without explicit acknowledgement and required env
- running Daedalus experiments inside Cerberus
- approving production imports from sandbox candidate packets

### Rust Local Review Replay

Lives as `cerberus-cli review-local` in `crates/cerberus-cli/`.

Responsibilities:

- parse local git-style diff files into `ReviewRequest.v1`
- preserve local diff source metadata and changed-file counts
- run the Rust review core through the same artifact surfaces as fixture review
- accept either a raw `ReviewConfig.v1` or a validated
  `ReviewerConfigPacket.v1` as the review config source
- write `review-request.json`, `review-run-artifact.json`, and `review-run.md`

Non-responsibilities:

- invoking Git or discovering repository state
- semantic routing, prioritization, or reviewer selection from diff contents
- live peer harness or provider execution
- hosted API compatibility

### Legacy Elixir Engine

Lives in `cerberus-elixir/`.

Responsibilities:

- accept review requests
- route / run reviewers
- aggregate verdicts
- expose HTTP endpoints
- persist run state

Retirement rule:

- none of these modules are deleted until
  `docs/shaping/legacy-surface-retirement.json` records parity evidence,
  deletion/archive commit, and rollback path.

## Historical Note

Older documents and walkthroughs may still reference the retired Python/Shell matrix pipeline. Those are historical artifacts, not current architecture.

ThinkTank review-bench artifacts are likewise historical donor material. The
migration inventory in `docs/shaping/thinktank-migration-inventory.md` records
which concepts were ported into Cerberus schemas and which runtime surfaces were
rejected.
