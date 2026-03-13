# PR 333 Walkthrough

## Merge Claim

Cerberus now treats indirect security/dataflow re-entry paths as first-class guard work and carries benchmark-derived replay coverage for the three cited misses in `#333`.

## Why This Matters

Before this branch, the security reviewer contract emphasized classic exploit classes but did not explicitly force reasoning over trusted-looking metadata, fail-open defaults, raw error leakage, async side-effect failures, or serialization/public-route exposure. The benchmark already showed those gaps in `bitterblossom#495`, `cerberus-cloud#94`, and `volume#417`.

After this branch:
- `.opencode/agents/security.md` contains a mandatory indirect re-entry pass
- `pi/skills/security-review/SKILL.md` mirrors the same categories
- `evals/promptfooconfig.yaml` contains replay-style security cases for all three benchmark misses
- tests lock the contract so future prompt drift fails locally

## Evidence Script

1. Show the RED gate that defined the work:
   - `python3 -m pytest tests/test_security_prompt_contract.py tests/test_evals_config.py -q`
   - Result before implementation: `7 failed`
2. Show the GREEN gate after the prompt/skill/eval updates:
   - `python3 -m pytest tests/test_security_prompt_contract.py tests/test_evals_config.py -q`
   - Result after implementation: `7 passed in 0.14s`
3. Show the persistent regression guard:
   - `make lint`
   - Result: `All checks passed!`
4. Show the full suite proof:
   - `make test`
   - Result: `1692 passed, 1 skipped in 50.12s`

## Before / After

### Before
- Guard guidance did not explicitly name the benchmarked indirect-path security shapes.
- The repo-level security skill stayed at a generic threat-model checklist.
- Promptfoo coverage had only generic security examples, not the replay cases tied to the cited misses.

### After
- Guard guidance now forces an explicit indirect re-entry reasoning pass.
- The security skill mirrors the same checklist so profile-driven runs keep the contract.
- Promptfoo includes replay-style fixtures for metadata re-entry, fail-open defaults, and error-leakage plus async-side-effect failures.

## Files To Review

- `.opencode/agents/security.md`
- `pi/skills/security-review/SKILL.md`
- `evals/promptfooconfig.yaml`
- `tests/test_security_prompt_contract.py`
- `tests/test_evals_config.py`

## Persistent Verification

- Primary check: `make test`
- Focused contract check: `python3 -m pytest tests/test_security_prompt_contract.py tests/test_evals_config.py -q`

## Residual Gap

This branch hardens the prompt and eval contract; it does not yet prove measured production recall improvement against live benchmark reruns. That remains follow-up validation work under `#331`.
