# Verify citation & anchor resolution (cheap deterministic oracle)

Priority: P2 · Status: pending · Estimate: S

## Goal
Reject confabulated or stale citations cheaply: every cited anchor/citation must resolve to real content — without Rust pretending to judge whether a finding is *faithful* (that's evals; see 015).

## Non-Goals
- No semantic-faithfulness enforcement (is the finding correct/useful) — that's a model + eval problem (015), not a Rust gate. Per ADR 0003.
- No new frozen taxonomy; `category` stays agent-free-form.

## Oracle
- [ ] Inline/file anchor path is in the change (already enforced); extend to: the line number is in range for the cited file when the workspace is available (repo_head+).
- [ ] When an anchor carries `hunk_digest` or a citation carries `excerpt`/`digest`, it matches the actual bytes at that location; a fabricated/stale quote fails validation.
- [ ] (dogfound, PR #466) the substrate honors `policy.external_research`: web tools are not granted when `external_research == Forbid`, so granted capability matches the declared tier.
- [ ] Every check is a real oracle — removing the model, a non-AI process still decides pass/fail. No heuristic stands in for meaning.

## Notes
**Why:** ADR 0003 + research (2026-06-23). The original 007 ("enforce groundedness in Rust") conflated *resolution* (a real oracle — keep, cheap, un-Goodhart-able) with *faithfulness* (no oracle — moved to evals/harness, 015). `validation.rs` already does the path-in-change check; this extends it to line/quote resolution, killing hallucinated citations for ~zero cost. Replaces the prior P0 "enforce groundedness" framing.
