# 004 - Daedalus Reviewer Config Promotion

Status: implemented-local-fixture
Priority: P1
Type: epic
Created: 2026-06-18

## Goal

Make Daedalus the research bench that discovers, evaluates, and promotes
reviewer configurations for Cerberus.

Cerberus should import measured reviewer configurations, not unscored prompts or
ad hoc model preferences.

## Oracle

A Daedalus delivery exports a signed or explicitly sandbox-only reviewer config
packet that Cerberus can validate, import, run against fixtures, and roll back.
The packet includes benchmark identity, score distribution, cost envelope,
model/provider/harness metadata, prompt/config hashes, promotion gate status,
and rollback metadata.

## Verification System

- `cerberus-cli validate-reviewer-config <packet>`
- `cerberus-cli import-reviewer-config <packet> --dry-run`
- A fixture run comparing the imported config against the current baseline and
  recording artifact deltas.
- Daedalus-side export test once the Cerberus packet schema exists.

## Scope

In scope:

- `ReviewerConfigPacket.v1` schema.
- Import validation and dry-run diffing.
- Baseline comparison artifact.
- Rollback metadata and provenance.
- Documentation of the Daedalus -> Cerberus handoff.

Out of scope:

- Running Daedalus experiments inside Cerberus.
- Treating raw benchmark wins as automatic production promotion.
- Giving Daedalus production posting authority.

## Evidence

- Daedalus owns specify/lab/contract stages and treats deploy/observe as
  replaceable consumer-plane surfaces.
- Daedalus ADR 004 requires member agents to write artifacts only and keeps
  production write authority behind later gates.
- Cerberus needs reviewer diversity to evolve quickly without making the engine
  itself a research workbench.

## Child Work

1. Define `ReviewerConfigPacket.v1`.
2. Add validation and dry-run import commands.
3. Add baseline comparison fixtures.
4. Coordinate Daedalus export shape.
5. Document promotion, rollback, and rejection rules.

## Notes

This depends on backlog 001's core config schema.

## Implementation Receipt

First local promotion delivery, 2026-06-18:

- Added `ReviewerConfigPacket.v1` and `ReviewerConfigImportReport.v1` schemas.
- Added `cerberus-cli validate-reviewer-config <packet>` and
  `cerberus-cli import-reviewer-config <packet> --dry-run`.
- Added a sandbox-only Daedalus packet fixture and checked dry-run report
  fixture for baseline comparison.
- Documented promotion, rollback, and rejection rules in
  `docs/shaping/daedalus-reviewer-config-promotion.md`.
