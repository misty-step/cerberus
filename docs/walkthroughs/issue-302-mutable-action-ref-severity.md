# Issue #302 Walkthrough: Mutable Action Ref Supply-Chain Severity

## Summary

This lane fixes a security-review blind spot in the `guard` prompt. Cerberus already reviewed GitHub Actions and secret handling, but it did not explicitly treat mutable third-party action refs plus forwarded secrets as a supply-chain threat class. The branch adds that guidance and locks it with a focused regression test.

## Before

- `guard` covered generic secret handling and infrastructure risk, but mutable GitHub Action refs were not called out as a first-class security check.
- The prompt did not name a severity ladder for mutable third-party refs versus mutable refs that also receive forwarded secrets.
- Safe exceptions were implicit rather than codified, so pinned refs and GitHub-owned semver actions were not clearly protected from over-reporting.

## After

- `guard` now runs a dedicated GitHub Actions supply-chain pass when workflow/config files change.
- Mutable third-party refs are explicitly at least `minor`.
- Mutable third-party refs with a sibling `secrets:` block forwarding an external API key are explicitly `major`, with concrete examples for what should and should not escalate.
- Full SHAs, semver tags, and GitHub-owned semver-pinned actions such as `actions/checkout@v4` are explicitly non-findings.
- GitHub-owned actions on mutable branch refs are now defined as a lower-risk case that can warrant `info`, rather than being left ambiguous.
- Regression tests fail if that prompt contract disappears.

## AC Verification Report (#302)

- ⚠️ PARTIAL: Given a PR diff containing `uses: owner/repo@master` with a sibling `secrets:` block passing any secret, when reviewed by `guard`, then a finding with severity `minor` or higher is emitted with category `supply-chain` or `security`.
  Evidence: `.opencode/agents/security.md` now requires mutable third-party refs to report at least `minor`, and `tests/test_infra_prompt_guidance.py` locks that language. This is prompt-contract evidence rather than a live LLM replay.
- ⚠️ PARTIAL: Given a PR diff containing `uses: owner/repo@master` with `secrets: api-key: ${{ secrets.SOME_API_KEY }}`, when reviewed by `guard`, then severity is `major`.
  Evidence: `.opencode/agents/security.md` now explicitly says to escalate to `major` when a sibling `secrets:` block forwards an external API key, and the regression test locks that clause.
- ⚠️ PARTIAL: Given a PR diff containing `uses: owner/repo@v1.2.3`, when reviewed by `guard`, then no supply-chain finding is emitted.
  Evidence: `.opencode/agents/security.md` now declares full SHAs and semver tags acceptable refs and `tests/test_infra_prompt_guidance.py` asserts that text is present.
- ⚠️ PARTIAL: Given a PR diff with `uses: actions/checkout@v4`, when reviewed by `guard`, then no supply-chain finding is emitted.
  Evidence: `.opencode/agents/security.md` now explicitly exempts GitHub-owned semver-pinned actions such as `actions/checkout@v4`, and the regression test locks that example.

Additional review hardening applied during `/pr-fix`:

- clarified the escalation boundary with concrete examples such as `AWS_ACCESS_KEY_ID`, `NPM_TOKEN`, `STRIPE_SECRET_KEY`, `SLACK_BOT_TOKEN`, and `GITHUB_TOKEN`
- removed the undefined edge case for GitHub-owned actions on mutable branch refs by explicitly treating them as lower-risk `info` candidates rather than third-party-equivalent findings

Gate: PASS WITH PARTIALS
Reason: all acceptance criteria are covered by explicit prompt-contract evidence plus regression tests, but no live LLM replay was added in this lane.

## Verification

Persistent verification for this path:

```bash
python3 -m pytest tests/test_infra_prompt_guidance.py -q
make validate
```

Observed result on this branch:

- `tests/test_infra_prompt_guidance.py`: `3 passed`
- `make validate`: `1577 passed, 1 skipped`
- `ruff`: clean
- `shellcheck`: clean

## Why This Is Better

The real defect was reviewer intent, not parser logic or verdict thresholds. This branch fixes the root cause at the security reviewer boundary, keeps the change small, and adds durable tests so the supply-chain severity rule cannot silently drift back to an under-graded `info` reading.
