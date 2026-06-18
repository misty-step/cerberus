# Project: Cerberus

## Vision

Cerberus is the source-agnostic review engine for the Misty Step agent stack.
It turns a change into a structured, high-signal review artifact through a
configurable panel of specialized reviewer agents.

**North Star:** any caller can submit a change and receive a trustworthy review
artifact without inheriting Cerberus internals or another caller's runtime.

## Product Shape

- **Target engine:** Rust library and CLI that accept versioned review requests
  and emit versioned review artifacts.
- **Optional service adapter:** HTTP dispatch/poll compatibility can wrap the
  Rust core, but is not the core engine boundary.
- **Current compatibility client:** root `action.yml` + `dispatch.sh`
- **Legacy donor engine:** `cerberus-elixir/`
- **Review data:** `defaults/`, `pi/agents/`, `templates/`
- **Callers:** Bitterblossom and Olympus may each call Cerberus through the
  request/artifact contract, but they must not know about each other.
- **Foundry:** Daedalus discovers, measures, and promotes reviewer
  configurations that Cerberus can import.

The retired Python/Shell matrix pipeline is no longer part of the supported repo
surface. The Elixir engine is now a compatibility surface and migration donor,
not the long-term implementation target.

## Domain Glossary

Canonical source: `docs/TERMINOLOGY.md`

| Term | Definition |
|------|-----------|
| Perspective | One review lens such as correctness, security, testing, or architecture |
| Reviewer | One LLM-powered reviewer agent inside the Cerberus engine |
| Verdict | Aggregated outcome for a review run: `PASS`, `WARN`, `FAIL`, or `SKIP` |
| Finding | A first-class issue claim emitted by a reviewer |
| Override | Authorized suppression of a failing verdict for a specific SHA |
| Review request | Versioned input describing the change, source metadata, context, and caller policy |
| Review artifact | Versioned output containing summary, findings, coverage, reviewer records, costs, and renderable projections |
| GitHub adapter | Compatibility adapter that acquires PR context and/or renders artifacts back to GitHub |
| Engine | The Rust core that runs reviewers and aggregates results; legacy behavior lives in `cerberus-elixir/` until ported |

## Active Focus

- Shape the Rust contract-first engine and prove it can replace the legacy
  Elixir review path.
- Preserve the existing GitHub action/API semantics as a compatibility adapter
  until the Rust path proves parity.
- Migrate the useful ThinkTank review-bench artifacts into Cerberus, then
  decommission ThinkTank as a separate review engine.
- Keep Bitterblossom and Olympus independent by enforcing contract-only caller
  integration.
- Import only measured Daedalus reviewer configurations, not unscored prompts.

## Quality Bar

- A review can be requested without assuming GitHub or pull requests.
- GitHub remains the first adapter, but GitHub posting policy stays outside the
  core engine.
- Completed reviews return a stable aggregated artifact, not just markdown.
- Consumer docs and templates match the actual adapter contracts.
- Legacy gates pass until Rust gates replace them; Rust work must add its own
  `cargo test`, schema fixture, and caller integration proof.

---
*Last updated: 2026-06-18*
