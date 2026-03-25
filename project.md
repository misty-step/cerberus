# Project: Cerberus

## Vision

Cerberus is a GitHub-native, multi-agent code review product. This repository now exposes that product through a thin GitHub Action client plus the Elixir review engine that backs it.

**North Star:** replace noisy AI review with a merge gate teams can trust.

## Product Shape

- **Client:** root `action.yml` + `dispatch.sh`
- **Engine:** `cerberus-elixir/`
- **Data:** `defaults/`, `pi/agents/`, `templates/`

The retired Python/Shell matrix pipeline is no longer part of the supported repo surface.

## Domain Glossary

Canonical source: `docs/TERMINOLOGY.md`

| Term | Definition |
|------|-----------|
| Perspective | One review lens such as correctness, security, testing, or architecture |
| Reviewer | One LLM-powered reviewer agent inside the Cerberus engine |
| Verdict | Aggregated outcome for a review run: `PASS`, `WARN`, `FAIL`, or `SKIP` |
| Finding | A first-class issue claim emitted by a reviewer |
| Override | Authorized suppression of a failing verdict for a specific SHA |
| OSS action | The GitHub Action in this repository that dispatches to the hosted API |
| Engine | The Elixir service in `cerberus-elixir/` that runs reviewers and aggregates results |

## Active Focus

- Make the API-dispatch path reliable enough to be a real merge gate.
- Keep docs, templates, and the action contract aligned with the Elixir engine.
- Remove stale compatibility surface whenever it stops paying for itself.

## Quality Bar

- Draft and fork PRs skip cleanly.
- Completed reviews return a stable aggregated verdict.
- Consumer docs and templates match the actual action contract.
- `cd cerberus-elixir && mix test` passes.
- `shellcheck dispatch.sh` passes.

---
*Last updated: 2026-03-24*
