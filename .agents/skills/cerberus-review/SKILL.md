---
name: cerberus-review
description: |
  Run Cerberus as an agent-native code reviewer. Use when an agent needs a
  review of a local git range, a verdict-gated exit code, an MCP review tool,
  artifact rendering/validation, or GitHub PR posting through an explicit
  caller-injected token. Do not use for generic code review advice without a
  checkout or ReviewArtifact.v1.
argument-hint: "[review-diff|mcp|render|validate|post-pr]"
---

# Cerberus Review

Cerberus is a caller-neutral review runner. The stable seam is
`ReviewRequest.v1 -> ReviewArtifact.v1`; GitHub is only a projection adapter.
Use the existing CLI or MCP server rather than reimplementing review logic.

## Fast Path: Local Agent Review

For a branch or committed range:

```sh
cerberus review-diff --base origin/master --head HEAD \
  --harness opencode \
  --model openrouter/z-ai/glm-5.2 \
  --allow-env OPENROUTER_API_KEY \
  --fail-on fail
```

stdout is the review. stderr is logs/errors.

Exit codes:

- `0`: valid review, verdict below the threshold.
- `1`: valid review, blocking verdict. Read stdout and fix the findings.
- `2`: Cerberus error; no trustworthy review was produced.

Use the fixture harness only for deterministic machinery tests:

```sh
cerberus review-diff --base <base> --head <head> \
  --harness fixture \
  --fixture-output fixtures/harness/valid-review.txt
```

## MCP

Start the stdio MCP server when the calling agent has an MCP client:

```sh
cerberus mcp
```

Tools are intent-shaped:

- `review_git_range`: review a committed local `base...head` range and return
  rendered review text plus verdict metadata.
- `render_review_artifact`: render a saved `ReviewArtifact.v1` to Markdown.
- `validate_review_artifact`: validate a saved artifact against its
  `ReviewRequest.v1`.

Prefer `review-diff` for shell-native agent loops; prefer MCP when the caller
benefits from tool schemas and structured results.

## GitHub Posting

Never let Cerberus post through ambient/keyring `gh` auth. `review-pr --post`
requires exactly one explicit token source:

```sh
cerberus review-pr --number <n> --repo owner/name \
  --harness opencode \
  --summary-target check-run \
  --gh-token-file /path/to/github-app-installation-token \
  --post
```

or:

```sh
cerberus review-pr --number <n> --repo owner/name \
  --harness opencode \
  --summary-target status \
  --gh-token-env GH_RELEASE_TOKEN \
  --post
```

GitHub App registration and token minting belong to the consumer or CI layer.
Cerberus only consumes an already-minted token and projects the artifact into
GitHub. Use `--dry-run` first when checking the post plan.

## Verification

Before claiming changes to Cerberus complete:

```sh
./scripts/verify.sh
```

For prompt, doctrine, substrate, or review-quality changes, also do the
repo-local live-review QA described by the `cerberus-qa` skill; the deterministic
gate does not prove reviewer quality.
