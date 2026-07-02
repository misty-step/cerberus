# Validate --openrouter-key-limit-usd is a sane positive value before minting

Priority: P1 · Status: ready · Estimate: S

## Goal
`mint_review_key`/`mint_key` (`src/openrouter_keys.rs:76,260`) forward
`--openrouter-key-limit-usd` straight into the OpenRouter provisioning API's
`limit` field with no validation — a `0`, negative, or accidentally-huge value
silently breaks the exact security guarantee 013 M1 exists to provide
(VISION.md: "make the model credential *worthless* ... per-review, capped,
revoked").

## Oracle
- [ ] `--openrouter-key-limit-usd` rejects `0` and negative values with a clear
      CLI-level error before any network call to mint a key (validate in
      `main.rs`, not deep inside `openrouter_keys.rs`).
- [ ] A unit test asserts `0.0` and `-1.0` are rejected with an error naming
      the flag and why (a non-positive cap defeats the "worthless key"
      guarantee).
- [ ] The existing default (`5.0`) and any explicit positive value continue to
      work unchanged.
- [ ] `./scripts/verify.sh` green.

## Notes
Verified live 2026-07-01: `grep -n "key_limit_usd" src/*.rs` shows the value
flows from CLI parse (`main.rs:293`, raw `f64`) straight to
`mint_review_key`/`mint_key` (`openrouter_keys.rs`) with no bounds check
anywhere in between.

**Why:** 013's whole M1 threat model (steal-and-replay, crash safety — both
live-verified 2026-07-01) depends on the key being genuinely capped; an
unvalidated `f64` limit is the one silent way to defeat a security control
that was otherwise rigorously proven live tonight.
