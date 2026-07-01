# Deploy Cerberus in three advisory modes

Priority: P1 | Status: ready | Estimate: M | Factory epic: 5

## Goal

Make the same Cerberus artifact usable from the three Factory deployment faces:
local CLI, pre-push or Dagger CI hook mode, and Bitterblossom-triggered PR
reviews. Every mode stays advisory until the consistency floor in `026` is met.

## Oracle

- [ ] Local CLI mode is documented and verified through `review-diff`: a caller
      gets review markdown/stdout, durable artifacts, and verdict-gated exit
      codes without GitHub or token requirements.
- [ ] Pre-push or Dagger CI hook mode runs Cerberus on a bounded diff, emits the
      artifact/receipt packet, and reports advisory status without blocking
      merges by default.
- [ ] Bitterblossom-triggered mode has a concrete integration contract:
      non-draft PR open and non-draft PR push events invoke Cerberus for
      whitelisted repos, then publish advisory comments/artifacts only.
- [ ] Each face uses the same `ReviewRequest.v1 -> ReviewArtifact.v1` kernel and
      differs only in trigger/context acquisition/projection.
- [ ] `./scripts/verify.sh` and one consumer-side smoke prove at least one
      non-local trigger path.

## Children

1. Preserve the shipped local handoff in
   `_done/018-agent-native-review-handoff.md` as the local face.
2. Add a CI/pre-push wrapper contract that calls the same CLI and writes
   artifacts under a predictable path.
3. Coordinate the Bitterblossom PR-trigger contract with its
   "Cerberus-on-BB" epic: trigger policy, whitelist, token source, receipt
   location, and advisory publication target.
4. Document the no-blocking rule until `026-consistency-floor.md` is satisfied.

## Notes

The deployment trio is about callers and triggers, not a new product boundary.
Cerberus stays caller-neutral; consumers own when it runs and where the result
is posted.
