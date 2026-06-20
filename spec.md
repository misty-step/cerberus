# Cerberus Restart Specification

Status: locked for MVP delivery.

## Purpose

Cerberus is a context-adaptive AI code review runner. It takes an arbitrary
change request, gives one strong master reviewer the richest trustworthy
context available through a selected agent substrate, and emits a durable
review artifact that callers can render or post in their own environment.

Cerberus is not a benchmark lab, hosted review platform, static reviewer swarm,
or GitHub-only action. It is a Rust application that owns contracts,
capability boundaries, execution receipts, artifact validation, and rendering.
The selected agent substrate owns agentic review execution.

## Core Product Rule

There is exactly one predefined reviewer agent: the Cerberus master.

Cerberus has no predefined correctness, security, architecture, QA, or research
subagents. The master reviewer decides at runtime whether to launch substrate
subagents, how many to launch, what perspectives matter, what system prompts
they receive, and what context they may inspect. The Rust application validates
capabilities and artifacts; it does not freeze reviewer topology into product
architecture.

This is deliberate. We invest in the general reviewing agent, prompt, tools,
context packaging, artifact grammar, and feedback loop instead of encoding
yesterday's best reviewer roles.

## Context Model

Cerberus reviews with whatever context it is actually given. It must never
claim evidence from a context tier it did not have.

Context tiers:

- `diff_only`: only the patch and request metadata are available. Review
  changed hunks only. Architecture and runtime claims must be phrased as
  uncertainty unless grounded in the diff.
- `repo_head`: the changed branch checkout is available. Cerberus may inspect
  related files, tests, config, local conventions, and build metadata.
- `repo_base_and_head`: both base and branch checkouts are available. Cerberus
  may compare behavior, deleted invariants, moved logic, changed contracts,
  and stale assumptions.
- `local_runtime`: a local build, test, CLI, API, browser, or container path
  is available. Cerberus may use runtime evidence when policy allows it.
- `remote_runtime`: a preview, dev, or staging endpoint is available. Cerberus
  may probe it only within explicit URL, credential, rate, and cleanup
  boundaries.

Each run records its observed `ContextCapabilities` in the final artifact.

## Substrate Decision

The MVP supports OpenCode, OMP, and a deterministic fixture harness. OpenCode is
the preferred production substrate because the current substrate report argues
that its server/session-first architecture fits durable automated review better
than wrapping a terminal-first local agent. OMP remains useful as a local
power-user and experimentation substrate.

This is not a return to predefined reviewers. OpenCode may make concurrent
sessions easier, but Cerberus still exposes one master reviewer contract and
lets that master design runtime lanes dynamically.

Substrate order for Cerberus:

1. `opencode`: default production-oriented master substrate; best fit for
   session events, concurrent reviewers, SDK/server operation, and future
   control-plane integration.
2. `omp`: local/power-user fallback; excellent tools and worktree subagents,
   less suitable as the durable organization-wide execution kernel.
3. `fixture`: deterministic verification only.

## External Evals

Cerberus does not own model or harness evaluation in the MVP. Daedalus and
other upstream laboratories may evaluate Cerberus, produce reviewer config
candidates, and compare harnesses or models. Cerberus only needs enough receipt
surface for those systems to replay and score runs later.

MVP excludes:

- model leaderboards;
- harness-vs-harness matrix runners;
- automatic reviewer config promotion;
- static eval dashboards;
- long-lived benchmark storage.

## Public Contracts

The stable public seam is:

```text
ReviewRequest.v1 + runtime policy -> ReviewArtifact.v1
```

Callers may be GitHub Actions, local CLIs, task systems, hosted workers, or
future services. They all acquire source context and map it into
`ReviewRequest.v1`. Cerberus returns immutable artifacts. Renderers and posters
project artifacts into Markdown, GitHub reviews, checks, SARIF, or other
surfaces without mutating the artifact.

### ReviewRequest.v1

Required fields:

- `schema_version`: `cerberus.review_request.v1`
- `request_id`: caller-provided stable id
- `source`: source kind and external identity
- `change`: title, optional description, diff, files, refs, and SHAs
- `context`: optional acceptance notes, instructions, artifacts, and available
  workspace/runtime locations
- `policy`: timeouts, degraded-run permission, research permission, render
  targets, and capability constraints

`source.kind` supports `local_diff`, `git_range`, `github_pr`, `external`, and
`fixture`.

### ReviewArtifact.v1

Required fields:

- `schema_version`: `cerberus.review_artifact.v1`
- `artifact_id`
- `request_id`
- `request_digest`
- `lifecycle_state`: `completed`, `completed_degraded`, `failed`, `skipped`,
  `cancelled`, or `stale`
- `verdict`: `PASS`, `WARN`, `FAIL`, or `SKIP`
- `context_capabilities`
- `summary`
- `findings`
- `comments`
- `suggested_fixes`
- `citations`
- `receipts`
- `run`
- `errors`

`completed_degraded` means the artifact is usable but records missing or failed
lanes. `failed` means no trustworthy verdict was produced.

## Evidence Discipline

Every finding must cite at least one concrete anchor:

- diff hunk or changed file line;
- repository file inspected from head or base;
- command output, test result, log, screenshot, or HTTP response;
- external source URL with observation time when external research was used.

External research is allowed only when policy permits it. External claims must
include citations. Model memory alone is not evidence.

## Master Harness

Rust launches the Cerberus master through a narrow harness boundary.

The harness must:

- write request and prompt material to private files, not argv;
- scrub inherited environment variables by default;
- pass only explicitly allowed provider keys and runtime variables;
- use an isolated session/profile path where practical;
- bound wall time and captured output;
- kill child processes on timeout;
- capture stdout/stderr as receipts;
- require exactly one marked `ReviewArtifact.v1` block in agent output;
- validate the artifact against the request digest and capabilities.

OpenCode invocation should start from this posture:

```text
opencode run --format json --dir <ephemeral-workspace-or-packet> \
  --file <prompt-file> --agent build
```

If attaching to a managed OpenCode server, the harness may add
`--attach <server-url>`.

The `build` agent is a substrate permission/profile default, not a
predefined Cerberus reviewer persona. Cerberus still defines one master review
contract; OpenCode profiles constrain how that master can inspect the provided
workspace. For repo-head context, Cerberus runs that profile inside a
disposable detached git worktree so model-side edits cannot mutate the user's
checkout.

OMP invocation remains supported as a fallback and should start from this
posture:

```text
omp -p --no-session --no-pty --no-extensions --no-skills --no-rules \
  --cwd <ephemeral-workspace-or-packet> @<prompt-file>
```

The exact command is represented in `execution_plan.json` with placeholders for
secret or private file paths.

## Master Reviewer Prompt Contract

The master prompt tells Cerberus:

- review only from available context;
- decide dynamically whether subagents are useful;
- if launching subagents, create focused lanes with explicit scope,
  system prompts, allowed context, and expected artifact shape;
- do not rely on predefined reviewer personas;
- synthesize lane evidence into one artifact;
- distinguish blocking findings from useful notes;
- avoid speculative findings when evidence is weak;
- produce exactly one `ReviewArtifact.v1` marker block.

## Runtime and Safety

MVP runtime is local process execution plus an ephemeral packet or workspace.
Containers and hosted workers are later hardening profiles behind the same
`ReviewHarness` contract.

Do not start by building:

- Docker/Podman as the default runtime;
- a hosted multi-tenant service;
- GitHub posting as the core execution path;
- direct provider API orchestration;
- semantic role selection in Rust.

Safety footguns to test:

- prompt or diff material appearing in argv;
- ambient `GH_TOKEN`, SSH agent, cloud credentials, or repo `.env` entering
  the child env;
- unbounded stdout/stderr;
- orphan child processes after timeout;
- invalid, multiple, or missing artifact marker blocks;
- artifact claims beyond declared context capabilities.

## CLI Surface

MVP CLI:

```text
cerberus request git-range --base <ref> --head <ref> --out <request.json>
cerberus request pr --number <n> --out <request.json>

cerberus review --request <request.json> --out <artifact.json> \
  [--markdown <review.md>] [--harness opencode|omp|fixture]

cerberus render --artifact <artifact.json> --markdown <review.md>
```

The request commands are acquisition helpers. They produce `ReviewRequest.v1`
and do not launch the reviewer or post comments. The review command remains
the only execution boundary.

The fixture harness exists only for deterministic verification. The preferred
production product path is the OpenCode harness; OMP is a local fallback.

## Verification System

Claim: Cerberus can turn a source-agnostic review request into a validated,
renderable review artifact while truthfully recording available context.

Falsifiers:

- a malformed request passes validation;
- an artifact with wrong request digest passes validation;
- an agent output with zero or multiple marker blocks is accepted;
- inline comments point outside changed files;
- external-research-backed findings lack citations;
- the child command receives prompt/diff content via argv;
- an ambient secret variable reaches the child env without policy approval.

Driver:

```text
./scripts/verify.sh
```

The verification script runs formatting, linting, unit tests, and a CLI smoke
review using fixture request/output data. The smoke run writes an artifact and
Markdown review under `target/cerberus/`.

Evidence packet:

- `target/cerberus/artifact.json`
- `target/cerberus/review.md`
- `target/cerberus/execution_plan.json`
- test output from `./scripts/verify.sh`

## MVP Acceptance

MVP is complete when:

- `spec.md` matches the implementation behavior;
- Rust types represent `ReviewRequest.v1`, `ContextCapabilities`, and
  `ReviewArtifact.v1`;
- request and artifact validation reject the falsifiers above;
- the fixture harness can produce a validated artifact;
- OpenCode and OMP harnesses build execution plans and can invoke their agent
  commands when selected;
- Markdown rendering works from stored artifacts;
- `./scripts/verify.sh` passes from a clean checkout;
- final git state is clean.

## Post-MVP

After MVP, consider:

- GitHub acquisition and posting adapters;
- rootless container runtime profile;
- base/head checkout acquisition helpers;
- remote runtime probe capability;
- Daedalus reviewer config import;
- SARIF/check renderers;
- richer receipt redaction and artifact storage.
