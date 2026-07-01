# Safe GitHub posting: explicit injected token, refuse ambient auth

Priority: P2 · Status: shipped · Estimate: S · Reshaped: 2026-06-25

**Shipped 2026-07-01:** `review-pr --post` now refuses ambient/keyring `gh`
auth and requires exactly one explicit token source (`--gh-token-file` or
`--gh-token-env`). The token is passed to PR acquisition, stale-head checks, and
`gh api` posting while ambient GitHub token env vars are removed for those
subprocesses. `./scripts/verify.sh` covers no-token refusal, explicit-token
fake-gh posting, and idempotent update behavior.

## Goal
When Cerberus posts a review to GitHub (`review-pr --post`), it uses an **explicit, caller-injected token** and **refuses to post under ambient/keyring (`gh`) user auth** — so it never silently posts as a human, and so a bot identity supplied by the caller (a GitHub App installation token) flows through cleanly, including check-runs.

## Reshape note (was: "Post reviews as Cerberus via a GitHub App")
The original ticket proposed creating a "Cerberus" GitHub App and baking `Cerberus[bot]` identity into Cerberus. That points the wrong way: spec.md says GitHub posting is a projection/"convenience orchestrator," **not the core execution path**, and VISION assigns *where results are posted* to the consumer. Prior art is unanimous (reviewdog/SARIF/PR-Agent/Danger/CodeRabbit/Greptile): **bot identity lives at the delivery boundary as injected config, never in the engine.** So this ticket keeps only the part that is genuinely Cerberus's — the **posting safety invariant** — and the App identity becomes a **consumer concern** (Bitterblossom / the operator's CI creates the App and injects its installation token). See [[cerberus-posting-boundary]]. The agent-native (no-GitHub) primary form factor is **018**.

## Non-Goals
- **No Cerberus-owned GitHub App, no baked identity.** Cerberus consumes whatever token it is given; it does not know or care that the token belongs to `Cerberus[bot]`.
- **No token minting / JWT in Cerberus.** Signing an App JWT → installation token is the caller's job (`actions/create-github-app-token` in CI, or a consumer helper). Cerberus receives an already-minted token.
- Posting stays an optional thin adapter (`post.rs`), not the core; not coupled to running inside GitHub Actions.

## Oracle
- [ ] `cerberus review-pr --post` posts **only** with an explicit injected token (`--gh-token-file <path>` or an explicit env var), and the `gh` subprocess uses that token — not the operator's keyring identity.
- [ ] With no explicit token (only ambient/keyring `gh` auth available), `--post` **refuses**: exits non-zero with an actionable message, posts nothing. (Dry-run / artifact emission still work without a token.)
- [ ] When the injected token is a GitHub App installation token, the posted comment/check author is that App's `*[bot]` identity (verified out-of-band) and `--summary-target check-run` succeeds — Cerberus is token-agnostic, so this is the same code path as a PAT with `checks:write`.
- [ ] `./scripts/verify.sh` green (fake-gh exercises the explicit-token path; the ambient-auth refusal is covered by a fixture that provides no token).
- [ ] A consumer doc (`docs/` or README) shows how Bitterblossom / CI creates the "Cerberus" App (perms: `pull_requests:write`, `checks:write`, `statuses:write`, `contents:read`; webhook off), mints an installation token, and injects it into `cerberus review-pr --post`.

## Children
1. **Posting safety (Cerberus-side, buildable/testable now):** accept an explicit posting token (`--gh-token-file`/env); set it for the `gh` subprocess; **refuse `--post` when only ambient auth is present**. Add `verify.sh` coverage for both (explicit-token posts; no-token refuses).
2. **Check-run with injected token:** confirm `--summary-target check-run` works with the injected token; keep `status` as the fallback.
3. **(Consumer, operator-gated) App creation + token minting doc:** the `Cerberus[bot]` App and `create-github-app-token` step live in the consumer's posting workflow, documented — not in Cerberus code.

## Verification System
- Claim: Cerberus posts to GitHub only with an explicit injected token and refuses ambient/keyring auth; a caller-supplied App token posts as `*[bot]` and creates check-runs through the same path.
- Falsifier: `--post` succeeds using only keyring/user auth with no explicit token; a posted comment shows the operator's human account; check-run creation fails with a valid injected token; dry-run/emission breaks without a token.
- Driver: `--gh-token-file <tok>` `review-pr --post` against a throwaway PR (or fake-gh) ⇒ posts; `--post` with no token ⇒ refuses non-zero.
- Grader: posted author login is the injected identity; the no-token `--post` exits non-zero and wrote nothing; `verify.sh` green.
- Evidence packet: posted comment/check author JSON + the refused-ambient-auth transcript.
- Cadence: on any change to the posting/auth path.

## Notes
**Why:** the dogfood (PR #466) posted as `phrazzld` because `gh` fell back to keyring auth — a real safety wart. The fix that belongs in Cerberus is the **refusal of ambient auth + explicit-token requirement**; the *identity* (an App) is the destination's concern, injected as a token. Decided 2026-06-25 (reshaped from the original GitHub-App framing after the posting-boundary brainstorm). The original "create + install a Cerberus App / mint tokens via openssl JWT" steps are preserved in git history and relocated to the consumer.
