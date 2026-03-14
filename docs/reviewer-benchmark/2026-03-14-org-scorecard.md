# Misty Step Reviewer Scorecard

Date: `2026-03-14`
Window reviewed: `2026-03-07` through `2026-03-14`
Scope: targeted high-signal repos `cerberus`, `bitterblossom`, `volume`, `cerberus-cloud`, and `gitpulse`

## Corpus

- `71` PRs updated in-window across `5` prioritized repos.
- Reviewer presence by PR:
  - `CodeRabbit`: `63`
  - `Gemini`: `63`
  - `Greptile`: `57`
  - `Codex connector`: `44`
  - `Cerberus`: `33`
  - `Claude`: `7`
- Repo coverage notes:
  - `misty-step/cerberus`: Cerberus present on `12/42` PRs.
  - `misty-step/volume`: Cerberus present on `8/11` PRs.
  - `misty-step/cerberus-cloud`: Cerberus present on `9/9` PRs.
  - `misty-step/gitpulse`: Cerberus present on `4/9` PRs.
  - `misty-step/bitterblossom`: `0` PRs updated in-window.
- Cerberus state buckets:
  - Cerberus absent on `38/71` PRs in the targeted corpus.
  - Cerberus present on `33/71` PRs.
  - Cerberus present with non-zero skip count on `12/33` PRs.
  - Skip-heavy presence remains concentrated in `cerberus-cloud` (`5/9`) and `cerberus` (`5/12`).
- Collector health:
  - No repo-level truncation warnings.
  - No missing-key skips surfaced in the collected review corpus.

## Recommended Reviewer Composition

### Default stack for important repos

- `Cerberus`
- `Gemini`
- `CodeRabbit`
- `Greptile`

Rationale:
- Cerberus is still the merge-gate system under active hardening and remains the best source of structured fix order when it runs cleanly.
- Gemini still produces the sharpest security/dataflow misses in the hardest examples from this window.
- CodeRabbit remains the best broad correctness foil, especially on concrete paging, contract, and edge-case behavior.
- Greptile remains strong on adjacent-regression and workflow/infra drift.

### Lean stack for lower-value repos

- `Cerberus`
- `Gemini`
- `CodeRabbit`

### Remove / disable

- No immediate removals from the comparison bench.
- `chatgpt-codex-connector` still does not produce enough differentiated signal to treat as a primary benchmark source.
- `Claude` appeared on only `7` PRs in this window and is still too sparse to drive priority-setting by itself.

## Cerberus Unique Catches

- `volume#418`: Cerberus was the clearest reviewer on the real merge-risk introduced by the reset rewrite. It called out the lost `aiReports` cleanup path and the missing production-guard test around `convex/test/resetUserData.ts`, which map directly to test isolation and data-safety regressions. Greptile's main finding on the same PR centered on dead-code cleanup in the retired mutation path; useful, but less merge-blocking.
- `cerberus#383`: Cerberus was materially stricter than peers on the new `repo_read` broker boundary. It surfaced a symlink escape in `resolveWorkspacePath`, a diff-header parsing bug for paths containing ` b/`, and an out-of-bounds slice invariant break, then pushed the missing regression tests that would have locked them. That is the clearest in-window proof that typed local-context retrieval can improve Cerberus when the contract is explicit and testable.

## Cerberus Misses

- `volume#417`: Cerberus warned, but `trace` skipped on a `+681 / -162` refactor and Gemini still surfaced the more important security/dataflow misses first: prompt-injection exposure through unfiltered roles and raw error leakage over SSE. Cerberus was present, not absent, but still behind on the highest-stakes findings.
- `cerberus-cloud#94`: Cerberus stayed mostly on architecture/configuration framing while Gemini called out the sharper fail-open egress default and corruption-risk paths. Cerberus was present with a skip and did not match the strongest security posture review on that PR.
- `gitpulse#184`: Cerberus warned while correctness skipped on a `+852 / -49` search rewrite. CodeRabbit and Claude stayed closer to the shipped correctness edge cases around review paging, result truncation, and time-slice behavior. This remains the cleanest in-window example of Cerberus being present but not leading on a large correctness-heavy PR.

## Overlap / Reinforcement

- `cerberus#377`: Cerberus, Gemini, and Greptile all aligned that the security-review contract hardening was directionally correct. This is useful reinforcement for `#333`, even though it is not an external proof of recall improvement yet.
- `cerberus#384`: Cerberus, Gemini, and Greptile all treated the confidence-normalization fix as a safe, narrow reliability patch. Cerberus stayed appropriately quiet instead of inventing noise, which is a positive signal on small parser/schema lanes.
- `volume#418`: Cerberus and Greptile both reacted to the reset/test surface, but Cerberus stayed closer to the actual merge-gate regressions while Greptile added useful surrounding cleanup pressure.

## Coverage Gaps

- Cerberus absence is still a first-order benchmark finding.
  - `misty-step/cerberus`: only `12/42` PRs in-window had Cerberus present.
  - `misty-step/gitpulse`: only `4/9` PRs had Cerberus present.
  - This still leaves too much of the benchmark in the "Cerberus never ran" bucket instead of the "Cerberus missed it" bucket.
- Cerberus skip pressure is still distorting the benchmark when Cerberus does run.
  - `volume#417`: correctness skipped.
  - `gitpulse#184`: correctness skipped.
  - `cerberus-cloud#94`: Cerberus present, but the run still included a skipped reviewer on a large security-sensitive PR.
- The current collector does not record draft state, so this report cannot quantify draft skips with the same confidence as reviewer presence. Draft-vs-live lane separation still has to be inferred from repo context, not the corpus schema.

## Improvement Hypotheses

### H1: Security/dataflow recall is still too weak on trusted-looking inputs and fail-open defaults

Observed in:
- `volume#417`
- `cerberus-cloud#94`

Hypothesis:
- Cerberus still underweights indirect re-entry paths such as role-bearing conversation history, raw error strings, and config defaults that silently widen attack surface.

Candidate fixes:
- Keep `#333` as the top security hardening track and replay both PRs as eval fixtures.
- Extend the new security contract work beyond prompt wording into more explicit context retrieval and adversarial replay coverage.

### H2: Large-PR timeout pressure still converts correctness/security lanes into partial review

Observed in:
- `volume#417`
- `gitpulse#184`

Hypothesis:
- High-risk slicing improved, but the benchmark has not yet shown enough downstream effect to declare the timeout blind spot closed.

Candidate fixes:
- Keep `#334` active until a future scorecard shows materially fewer large-PR correctness/security skips.
- Add replay fixtures that specifically verify the bug classes Cerberus missed first on these two PRs.

### H3: Typed reviewer context retrieval is now benchmark-backed and should be treated as a concrete hardening lane

Observed in:
- `cerberus#383`

Hypothesis:
- Cerberus gets materially stronger when local repo context is available through an explicit, bounded, typed interface instead of only prompt stuffing plus generic filesystem tools.

Candidate fixes:
- Treat `#57` as an active benchmark-backed track, not a vague future improvement.
- Add replay coverage for symlink traversal, diff-header path parsing, and bounded slice invariants in the repo broker surface.

### H4: Self-dogfood reviewer presence is still too inconsistent to measure recall honestly

Observed in:
- `misty-step/cerberus`: `12/42` PRs with Cerberus present
- `misty-step/gitpulse`: `4/9` PRs with Cerberus present

Hypothesis:
- Workflow rollout and trigger hygiene still leave too many core-repo PRs outside the Cerberus lane, weakening the benchmark as a decision tool.

Candidate fixes:
- Keep `#375` active as operational benchmark infrastructure.
- Track Cerberus absence explicitly in each future scorecard before making recall claims.

## Experiment Backlog

### `P0`

- `#333` Security/dataflow blind-spot hardening
  - Replay fixtures: `volume#417`, `cerberus-cloud#94`
- `#334` Large-PR correctness/security blind-spot reduction
  - Replay fixtures: `volume#417`, `gitpulse#184`

### `P1`

- `#57` Reviewer context retrieval
  - Benchmark evidence: `cerberus#383`
  - Lock the `repo_read` / `github_read` context split and harden the boundary with concrete security/correctness fixtures.
- `#335` Lifecycle and state-machine challenger lane
  - No new decisive evidence this run, but prior `bitterblossom` misses still stand.
- `#336` Adjacent-regression checks for workflow and infra PRs
  - Keep `volume#418` in the replay set alongside `volume#407`.
- `#375` Reviewer presence / self-dogfood coverage
  - Treat absence on `cerberus` and `gitpulse` as an operational benchmark blocker.

## Backlog Translation

- Keep `#333`, `#334`, `#335`, `#336`, and `#375` active.
- Add `#57` explicitly to the benchmark-backed hardening stack; `cerberus#383` is now concrete evidence that context retrieval shape changes reviewer quality.
- Do not lower pressure on large-PR reliability yet; `volume#417` and `gitpulse#184` are still active evidence even after `#379` landed.
- Treat this run as a reinforcement of the existing reviewer-composition recommendation, not a reason to change the default comparison bench.
