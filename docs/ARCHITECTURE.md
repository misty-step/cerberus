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
`PeerHarnessCommandProfiles.v1` records the future protocol runner command and
the underlying peer CLI template; raw peer CLIs do not define the Cerberus
input/output contract.

`cerberus-peer-harness` is the Rust protocol command named by those profiles.
It currently proves file handoff and artifact validation offline by emitting a
degraded `SKIP` artifact with exact request coverage. It can also render a
deterministic prompt and parse exact marked local transcript fixtures into
reviewer artifacts. It does not call Pi/Goose/OpenCode/OMP or spend provider
budget.

## Request Flow

```text
pull_request event
    │
    ▼
action.yml
    │
    ▼
dispatch.sh
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
- `dispatch.sh`
- `templates/consumer-workflow-reusable.yml`
- `bin/cerberus.js`

Responsibilities:

- validate basic PR context
- dispatch to the API
- poll until completion
- expose workflow outputs

### Rust Adapter SDK

Lives in `crates/cerberus-adapter/`.

Responsibilities:

- build and validate caller-shaped `ReviewRequest.v1` values
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
- parse local transcripts that contain exactly one marked reviewer artifact JSON
  block
- validate parsed artifacts against the core reviewer/request acceptance rule
- fail closed if live peer execution is requested

Non-responsibilities:

- peer CLI invocation
- free-form transcript interpretation
- model budget or quality evaluation

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
