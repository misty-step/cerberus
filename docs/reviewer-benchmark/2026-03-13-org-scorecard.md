# Misty Step Reviewer Scorecard

Date: `2026-03-13`
Window reviewed: `2026-03-06` through `2026-03-13`
Scope: targeted high-signal repos `cerberus`, `bitterblossom`, `volume`, `cerberus-cloud`, and `gitpulse`

## Corpus

- `64` PRs updated in-window across `5` prioritized repos.
- Reviewer presence by PR:
  - `GitHub Actions`: `63`
  - `CodeRabbit`: `55`
  - `Gemini`: `55`
  - `Greptile`: `49`
  - `Cerberus`: `29`
  - `Codex connector`: `40`
  - `Claude`: `9`
- Repo coverage notes:
  - `misty-step/cerberus`: Cerberus present on `5/32` PRs.
  - `misty-step/volume`: Cerberus present on `10/13` PRs.
  - `misty-step/cerberus-cloud`: Cerberus present on `10/10` PRs.
  - `misty-step/gitpulse`: Cerberus present on `4/9` PRs.
  - `misty-step/bitterblossom`: `0` PRs updated in-window.
- Preflight / coverage gaps:
  - `13` draft skips in the targeted sample.
  - No missing-key skips surfaced in this run.

## Recommended Reviewer Composition

### Default stack for important repos

- `Cerberus`
- `CodeRabbit`
- `Gemini`
- `Greptile`

Rationale:
- Cerberus remains the merge-gate system under improvement and still produces the best structured fix ordering when it runs.
- Gemini continues to surface the sharpest security/dataflow misses in this window.
- CodeRabbit remains strong on concrete implementation bugs and shape/edge-case failures.
- Greptile is still the best adjacent-regression checker on workflow and infra changes.

### Lean stack for lower-value repos

- `Cerberus`
- `Gemini`
- `CodeRabbit`

### Remove / disable

- No immediate removals from the benchmark comparison bench.
- `chatgpt-codex-connector` still reads mostly as boilerplate in this window and should not be treated as a primary benchmark source.

## Cerberus Unique Catches

- `volume#407`: Cerberus was the clearest reviewer on the actual merge-gate break. It called out the renamed status-context mismatch in `release-please.yml` and the fake-success status being posted under the old context, while other reviewers stayed broader or non-actionable.
- `volume#418`: Cerberus caught concrete reset-path regressions that peers did not prioritize first, especially the dropped `aiReports` cleanup path in `src/app/api/test/reset/route.ts` and the missing production-guard test around `convex/test/resetUserData.ts`.

## Cerberus Misses

- `volume#417`: Cerberus warned on SSE cascade failure and timed out the correctness lane, but Gemini still surfaced the more important security/dataflow misses first: prompt-injection exposure through unfiltered roles and raw error leakage over SSE.
- `cerberus-cloud#94`: Cerberus stayed mostly on architecture/configuration framing, while Gemini called out the fail-open egress default, SQL interpolation risk, and silent JSON corruption path.
- `gitpulse#184`: Cerberus produced mostly architecture feedback while `trace` timed out. CodeRabbit stayed closer to the shipped bug and caught the incomplete handling around GitHub Search result limits and paging behavior.

## Overlap / Reinforcement

- `volume#418`: Cerberus and Greptile both pushed on the reset/test-safety surface, but from different angles. Cerberus emphasized lost cleanup coverage and production-guard verification; Greptile emphasized dead-code drift and misleading comments around the retired mutation path.
- `gitpulse#184`: Cerberus and CodeRabbit both reacted to the search-window refactor, but Cerberus framed the design leakage while CodeRabbit found the concrete edge-case behavior. This is useful reinforcement, but it still favors the competitor on correctness recall.

## Coverage Gaps

- Cerberus absence is now a first-order benchmark finding, not noise.
  - On `misty-step/cerberus`, Cerberus only appeared on `5/32` PRs in the sampled window.
  - On `misty-step/gitpulse`, Cerberus appeared on `4/9` PRs.
  - This means too many benchmark candidates still fall into the "Cerberus never ran" bucket instead of "Cerberus missed it."
- Large-review pressure still distorts lane quality even when Cerberus runs.
  - `volume#417`: correctness timed out on a `+681 / -162` refactor.
  - `gitpulse#184`: correctness timed out on a `+852 / -49` search rewrite.
- Draft preflight skips are healthy when intentional, but the benchmark must continue separating them from true misses.

## Improvement Hypotheses

### H1: Security/dataflow recall is still too weak on trusted-looking inputs and fail-open defaults

Observed in:
- `volume#417`
- `cerberus-cloud#94`

Hypothesis:
- Cerberus still underweights indirect re-entry paths such as role-bearing conversation history, raw error strings, and defaulted config that silently weakens network or data-handling posture.

### H2: Large-PR timeout pressure is still converting correctness/security lanes into partial architecture review

Observed in:
- `volume#417`
- `gitpulse#184`

Hypothesis:
- High-risk slices still are not reaching `trace` and `guard` early enough, so the system spends too much budget on broad context before reviewing the sharp edges.

### H3: Adjacent-regression recall improved, but the repo still needs a stable workflow/infra challenger habit

Observed in:
- `volume#407`
- `volume#418`

Hypothesis:
- Cerberus is now better at naming workflow and CI truthfulness bugs, but it still needs consistent neighboring-file and deleted-path inspection to keep pace with Greptile on infra drift.

### H4: Self-dogfood reviewer presence is too inconsistent to measure recall honestly

Observed in:
- `misty-step/cerberus` sample: `5/32` PRs with Cerberus present
- `misty-step/gitpulse` sample: `4/9` PRs with Cerberus present

Hypothesis:
- Workflow triggers and repo rollout are still leaving too many PRs outside the benchmarkable Cerberus lane, which hides real recall gaps and weakens the scorecard as a source of truth.

## Experiment Backlog

### `P0`

- `#333` Security/dataflow blind-spot hardening
  - Use `volume#417` and `cerberus-cloud#94` as replay fixtures.
- `#334` Large-PR correctness/security blind-spot reduction
  - Use `volume#417` and `gitpulse#184` as timeout/partial-review fixtures.

### `P1`

- `#335` Lifecycle and state-machine challenger lane
  - Keep the benchmark evidence from `bitterblossom` in scope even though that repo had no in-window PRs this run.
- `#336` Adjacent-regression checks for workflow and infra PRs
  - `volume#407` remains the clearest replay fixture.
- Reviewer presence / self-dogfood coverage
  - Treat low Cerberus presence on `cerberus` and `gitpulse` as an operational reliability issue, not just a benchmark footnote.

## Backlog Translation

- Keep `#333`, `#334`, `#335`, and `#336` as the benchmark-driven recall hardening spine for `#331`.
- Add reviewer-presence monitoring to the active benchmark loop so future scorecards report "Cerberus absent" explicitly before making recall claims.
- Continue treating `docs/reviewer-benchmark/` as the source of truth for the benchmark program, with backlog changes recorded only when the new run materially changes priority.
