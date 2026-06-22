# Post reviews as Cerberus via a GitHub App

Priority: P1 · Status: ready · Estimate: M

## Goal
Cerberus posts its reviews under a branded `Cerberus[bot]` identity (not the operator's user account), using a GitHub App installation token, and can write real check-runs.

## Non-Goals
- Not coupling posting to running inside GitHub Actions (the App token works from any runner).
- Not baking a single global identity into Cerberus — the token/identity is caller-injected (consumers may use their own App).

## Oracle
- [ ] A "Cerberus" GitHub App exists (perms: pull_requests:write, checks:write, statuses:write, contents:read), installed on `misty-step/cerberus`.
- [ ] `cerberus review-pr --post` with the App installation token posts the summary comment, inline comments, and status/check as `Cerberus[bot]`, not as a user.
- [ ] Cerberus refuses to `--post` with ambient user auth (no silent posting as a human); the posting token is explicit.
- [ ] `--summary-target check-run` works (App can create check-runs) and renders the Cerberus verdict.

## Children
1. **(Operator) Create + install the App** — name, avatar, permissions above, webhook disabled; generate the private key; install on the repo; store App ID + private key as secrets.
2. **Token minting** — a helper (Rust util, or `scripts/` shell using an openssl-signed JWT → installation token) that mints a short-lived installation token from App ID + private key. In CI use `actions/create-github-app-token`.
3. **Cerberus-side token injection + safety** — accept an explicit posting token (`--gh-token-file` / env); refuse `--post` when only ambient user auth is present. (Buildable/testable without the App.)
4. **Check-run upgrade** — default `--summary-target check-run` when an App token is present; keep `status` as the user-token fallback.
5. **Consumer doc** — how Bitterblossom / Olympus install the App (or use their own) and inject the token.

## Notes
**Why:** the dogfood (PR #466) posted as `phrazzld` because `gh` fell back to keyring auth. The posting path already honors `GH_TOKEN`, so the only gap is identity: a GitHub App gives `Cerberus[bot]` + check-runs + short-lived scoped tokens with no seat — how CodeRabbit/Dependabot work, and aligned with VISION (identity is the destination's concern; Cerberus stays the engine). App creation is operator-gated (browser/manifest); everything else is Cerberus-side. Decided 2026-06-22 (brainstorm: App over machine-user / Actions-bot).
