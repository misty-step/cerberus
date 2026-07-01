# Diagnose GLM 5.2 opencode artifact timeout

Priority: P2 · Status: pending · Estimate: S

## Goal

Make the live `opencode` + OpenRouter GLM 5.2 review path emit a valid
`ReviewArtifact.v1` within the configured Cerberus timeout when reviewing the
small diff-only fixture.

## Context

PR #484 fixed the misleading model-resolution failure: `openrouter/z-ai/glm-5.2`
is available to opencode when `OPENROUTER_API_KEY` is passed into Cerberus's
scrubbed child environment with `--allow-env OPENROUTER_API_KEY`.

After that fix, the live GLM path no longer fails as `ProviderModelNotFoundError`.
It reaches opencode, but a short full Cerberus review attempt timed out on each
attempt without writing `review-artifact.json`.

## Oracle

- [ ] `cerberus review --request fixtures/requests/diff-only.json --harness
      opencode --model openrouter/z-ai/glm-5.2 --allow-env OPENROUTER_API_KEY
      --out <artifact> --transcript <transcript> --receipt-bundle <receipt>`
      emits a valid artifact and receipt on the diff-only fixture.
- [ ] The transcript shows at least one complete model turn that either writes
      the artifact or gives an actionable schema/prompt failure. A silent timeout
      with only `step_start` is not acceptable.
- [ ] If GLM 5.2 needs a longer default timeout, the timeout is explicit in docs
      or config and does not mask artifact-emission failures.

## Evidence From Initial Diagnosis

- OpenRouter live catalog lists `z-ai/glm-5.2`; opencode lists it as
  `openrouter/z-ai/glm-5.2`.
- A scrubbed direct opencode call with only `OPENROUTER_API_KEY` passed returned
  `OK` for `opencode run 'Say OK.' --format json --model
  openrouter/z-ai/glm-5.2 --agent build`.
- A full Cerberus run with `--allow-env OPENROUTER_API_KEY` and
  `--timeout-seconds 20` reached opencode but timed out three times without
  creating `review-artifact.json`; transcript attempts contained only
  `step_start` events.

## Boundary

Do not re-open model availability unless the provider catalog changes. Treat
this as a prompt, timeout, re-ask, or artifact-emission problem. Cerberus owns
the runner and artifact contract; Crucible/Daedalus own scoring the resulting
receipt once it exists.
