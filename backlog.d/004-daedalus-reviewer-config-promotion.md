# 004 - Daedalus Reviewer Config Promotion

Status: cerberus-ready-daedalus-export-pending
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

- [x] Define `ReviewerConfigPacket.v1`.
- [x] Add validation and dry-run import commands.
- [x] Add baseline comparison fixtures.
- [x] Coordinate Daedalus export shape.
- [x] Document promotion, rollback, and rejection rules.

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

Packet-backed review execution bridge, 2026-06-19:

- Backlog 020 lets `cerberus-cli review` and `cerberus-cli review-local` use a
  validated `ReviewerConfigPacket.v1` directly through `--config-packet`.
- This closes the manual `.config` extraction gap for sandbox review runs. It
  still does not approve or install reviewer defaults.

Cross-repo Daedalus export boundary, 2026-06-19:

- Added `docs/shaping/004-daedalus-cross-repo-export-closeout-plan.html` to
  separate the Cerberus import contract from Daedalus' generic control-plane
  `launch-pack` TOML packets.
- Updated Daedalus `DESIGN.md` on branch
  `cerberus/004-reviewer-config-handoff` at commit `38a7e67` to name Cerberus
  as a downstream reviewer-config consumer that requires
  `ReviewerConfigPacket.v1` JSON, not a generic plane import packet.
- Added Daedalus `backlog.d/046-export-cerberus-reviewer-config-packet.md` as
  the owned implementation ticket for the missing exporter and Cerberus
  validation loop.
- Current state: Cerberus can validate, dry-run import, and sandbox-run the
  checked Daedalus-style fixture packet. That fixture is not claimed as output
  from a Daedalus exporter. Daedalus still must implement the exporter before
  this becomes an end-to-end Daedalus -> Cerberus promotion path; no reviewer
  defaults or production posting authority are approved.
- Verified the sandbox run with `cargo run --locked -p cerberus-cli -- review
  --fixture fixtures/review-request/clean.json --config-packet
  fixtures/reviewer-config-packets/daedalus-sandbox-reviewer-config.json --out
  tmp/reviewer-config/packet-review`.
