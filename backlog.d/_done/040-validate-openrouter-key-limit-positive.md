# Validate --openrouter-key-limit-usd is a sane positive value before minting

Priority: P1 · Status: done (2026-07-03) · Estimate: S

## Goal
`mint_review_key`/`mint_key` (`src/openrouter_keys.rs:76,260`) forward
`--openrouter-key-limit-usd` straight into the OpenRouter provisioning API's
`limit` field with no validation — a `0`, negative, or accidentally-huge value
silently breaks the exact security guarantee 013 M1 exists to provide
(VISION.md: "make the model credential *worthless* ... per-review, capped,
revoked").

## Oracle
- [x] `--openrouter-key-limit-usd` rejects `0` and negative values with a clear
      CLI-level error before any network call to mint a key. Validated in
      `mint_scoped_openrouter_key` (`main.rs`) before `mint_review_key` is
      ever called.
- [x] Unit test `mint_scoped_openrouter_key_rejects_non_positive_limit_before_any_network_call`
      asserts `0.0` and `-1.0` are both rejected, error names
      `--openrouter-key-limit-usd` and "positive".
- [x] Existing default (`5.0`) and explicit positive values unchanged — no
      other test in the suite regressed.
- [x] `./scripts/verify.sh` green.

## Notes
Verified live 2026-07-01: `grep -n "key_limit_usd" src/*.rs` shows the value
flows from CLI parse (`main.rs:293`, raw `f64`) straight to
`mint_review_key`/`mint_key` (`openrouter_keys.rs`) with no bounds check
anywhere in between.

**Why:** 013's whole M1 threat model (steal-and-replay, crash safety — both
live-verified 2026-07-01) depends on the key being genuinely capped; an
unvalidated `f64` limit is the one silent way to defeat a security control
that was otherwise rigorously proven live tonight.
