# Emit ReviewArtifact via structured output; delete defensive parsing

Priority: P1 · Status: pending · Estimate: M

## Goal
Stop fighting the model into a hand-specified JSON shape. Emit `ReviewArtifact.v1` via the model's native structured output (JSON-schema / tool-calling), simplifying the prompt and deleting the defensive extraction that exists only because the prose contract is unreliable.

## Non-Goals
- The artifact CONTRACT stays (it's the product); only the emission MECHANISM changes.
- No loosening of validation (that's the legit waist, ADR 0003).

## Oracle
- [ ] `build_opencode_message`/`build_master_prompt` no longer carry the ~1800-char field-by-field JSON-shape lecture; the schema is supplied as a structured-output / tool spec (OpenCode supports a custom provider `baseURL` + openai-compatible structured outputs — confirm the model+OpenCode path).
- [ ] The marker / XML / raw-JSON fallback extraction in `harness.rs` is deleted or reduced to a thin guard; the real-model artifact-validity rate (per 015) is ≥ the prose-contract baseline.
- [ ] Schema drift like the `Edit.replacement` null failure cannot recur — the schema is enforced at decode, not by prose.

## Notes
**Why:** ADR 0003 + delete-first. The hand-rolled prose contract already caused the `Edit.replacement` drift and the convergence timeout (PR #466), and spawned the defensive marker/XML/raw parser in `harness.rs`. Structured output (OpenAI structured outputs ~100% schema compliance vs <40% for prose, 2024) is the model-native fix: simpler prompt, fewer failures, less code. Measure the validity-rate delta via 015. This is "let the model do what it's good at" applied to the output contract.
