# Misty Step Reviewer Scorecard

Date: `2026-03-08`
Window reviewed: `2026-03-01` through `2026-03-08`
Scope: Misty Step org PRs, open and closed, with focus on `bitterblossom`, `cerberus`, `cerberus-cloud`, `cerberus-web`, and `volume`

## Corpus

- `287` PRs updated in-window across `55` repos.
- Reviewer presence by PR:
  - `CodeRabbit`: `235`
  - `Greptile`: `229`
  - `Gemini`: `218`
  - `Cerberus`: `208`
  - `Codex connector`: `139`
  - `Claude`: `31`
- Cerberus verdict distribution:
  - `PASS`: `89`
  - `WARN`: `107`
  - `FAIL`: `12`
- Cerberus skip pressure:
  - `57` draft skips
  - `29` missing-key skips

## Recommended Reviewer Composition

### Default stack for important repos

- `Cerberus`
- `CodeRabbit`
- `Greptile`
- `Gemini`
- `Claude`

Rationale:
- Cerberus is the required merge-gate swarm and should stay the primary system under active improvement.
- CodeRabbit and Greptile were the strongest competitors in this window for concrete implementation bugs and “PR says X, code still fails Y” mismatches.
- Gemini produced lower average signal than CodeRabbit/Greptile but still caught several real security/data-handling misses.
- Claude had low coverage but high-quality architecture/security findings when present.
- The `chatgpt-codex-connector` was mostly boilerplate in this window and did not justify its noise footprint.

### Lean stack for lower-value repos

- `Cerberus`
- `Greptile`
- `Gemini`

### Immediate composition change

- Remove `chatgpt-codex-connector` wherever it is enabled unless a repo demonstrates repo-specific value later.

## Cerberus Strengths

- Strongest on workflow and CI truthfulness.
  - `volume#407`: caught status-context mismatch and fake-success status posting.
  - `volume#406`: caught diff-range scanning edge-case in push-to-default-branch flow.
- Strongest on resilience and cascade-failure thinking.
  - `volume#417`: caught backend execution continuing after SSE write failure.
  - `cerberus-cloud#77`: caught oversized summary comment risk breaking reporting.
- Strong on concrete operational correctness.
  - `cerberus-cloud#93`: caught uncaught async audit-log rejection risk.
  - `volume#410`: caught escaped-newline validation bug in shell logic.
- Strong on missing negative-path coverage.
  - `cerberus-cloud#90`, `cerberus-web#5`, `volume#399`, `volume#417`.

## Cerberus Misses

- Missed subtle security/dataflow bugs that other reviewers surfaced first.
  - `bitterblossom#495`: Gemini and CodeRabbit caught remaining prompt-injection paths through raw title/branch exposure; Cerberus only warned on maintainability.
  - `cerberus-cloud#94`: Gemini caught egress-allowlist default bypass, SQL interpolation risk, and silent JSON corruption paths; Cerberus stayed on maintainability.
- Passed state-machine / loop-scope bugs other reviewers caught.
  - `bitterblossom#509`: Cerberus passed; CodeRabbit and Greptile caught `builder_handoff_recorded` being too wide in scope and able to swallow later real failures.
  - `bitterblossom#477`: Greptile caught the blocked-issue retry loop; Cerberus passed.
- Lost coverage on larger refactors when correctness/security lanes timed out.
  - `volume#401`: Cerberus passed with `trace` and `guard` skipped; Claude, Gemini, and CodeRabbit still found date, unit, and error-leakage issues.
- Missed adjacent-file regressions when the headline bug was elsewhere.
  - `volume#407`: Greptile also caught deleted review-workflow coverage and weakened `trufflehog` enforcement that Cerberus did not prioritize.

## Reviewer-by-Reviewer Delta

### Cerberus vs CodeRabbit

- Cerberus wins on structured gatekeeping, fix ordering, and workflow/resilience hazards.
- CodeRabbit wins on subtle implementation bugs, hidden control-flow defects, and residual security leaks.

### Cerberus vs Greptile

- Cerberus wins on merge-gate / CI correctness and negative-path coverage.
- Greptile wins on acceptance-criteria mismatch, root-cause control-flow gaps, and “this still does not actually satisfy the stated change” findings.

### Cerberus vs Gemini

- Cerberus is more consistent and more operationally grounded.
- Gemini is better at some configuration-default and data-handling security bugs when it goes beyond summary mode.

### Cerberus vs Claude

- Cerberus has far better coverage.
- Claude, when present, often had deeper architecture/security/performance reasoning than Cerberus on the same PR.

### Cerberus vs Codex connector

- Cerberus was materially more useful.
- In this window the Codex connector did not supply enough substantive findings to justify continued inclusion.

## Improvement Hypotheses

### H1: Cerberus under-detects security bugs when untrusted data re-enters through “trusted-looking” fields

Observed in:
- `bitterblossom#495`
- `cerberus-cloud#94`
- `volume#417`

Hypothesis:
- The security lane overweights explicit auth/secrets/injection signatures and underweights indirect re-entry paths such as titles, branch names, defaulted env behavior, error strings, and response serialization.

### H2: Cerberus is too fragile on large PRs because correctness/security are losing the budget race

Observed in:
- `volume#401`
- multiple larger `bitterblossom` and `gitpulse` refactors

Hypothesis:
- Diff/context packaging is too coarse, so `trace` and `guard` time out before they reach the highest-risk slices.

### H3: Cerberus is weaker than CodeRabbit/Greptile at state-machine and lifecycle bugs spanning multiple phases

Observed in:
- `bitterblossom#509`
- `bitterblossom#477`

Hypothesis:
- Prompts do not force explicit phase-by-phase reasoning over “what becomes true after this point, and what later handlers now do incorrectly?”

### H4: Cerberus misses adjacent regressions because it stays too close to the obvious diff intent

Observed in:
- `volume#407`

Hypothesis:
- Reviewers need a “neighboring file / deleted file / weakened guardrail” checklist, especially on workflow and infra PRs.

## Proposed Experiments

### P0: Security/Dataflow Recall Hardening

- Add a mandatory security checklist for:
  - untrusted title/slug/branch reuse
  - defaulted config that weakens security posture
  - raw error leakage
  - async logging / fire-and-forget failure paths
  - serialization and public-route exposure
- Add adversarial eval cases drawn from:
  - `bitterblossom#495`
  - `cerberus-cloud#94`
  - `volume#417`

### P0: Large-PR Slice Strategy

- Before `trace`/`guard`, split changed files into high-risk slices and feed those first.
- Add a fallback path: if a reviewer is nearing timeout, it must emit a partial high-risk review instead of mostly skipping.
- Track timeout rate by perspective and PR size bucket.

### P1: State-Machine Challenger Lane

- Add a challenger prompt for lifecycle bugs:
  - “What flags become sticky?”
  - “What later handlers now misclassify?”
  - “What loops re-queue blocked work forever?”
- Seed evals from:
  - `bitterblossom#509`
  - `bitterblossom#477`

### P1: Adjacent-Regression Checklist

- For workflow/infra PRs, require each reviewer to inspect:
  - deleted files
  - renamed status contexts
  - changed enforcement flags
  - neighboring workflows or scripts that depend on the edited surface

### P1: Reviewer-Context Retrieval Upgrade

- Pull prior PR review comments, author “PR Unblocked” summaries, and linked issue acceptance criteria into review context by default.
- The goal is to let Cerberus reason over active debate, not just the raw diff.

## Backlog Translation

- `P0` Security/dataflow blind-spot hardening.
- `P0` Large-PR timeout reduction for `trace` and `guard`.
- `P1` State-machine challenger lane and eval pack.
- `P1` Adjacent-regression checks for workflow / infra PRs.
- `P1` Weekly reviewer benchmark loop using the repo-local `.agents/skills/reviewer-benchmark` skill.
