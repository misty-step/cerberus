#!/usr/bin/env bash
set -euo pipefail

resolved_key="${INPUT_API_KEY:-}"
if [[ -z "$resolved_key" ]]; then
  if [[ -n "${INPUT_KIMI_API_KEY:-}" ]]; then
    resolved_key="${INPUT_KIMI_API_KEY}"
    invoked_ref="${GITHUB_ACTION_REF:-v2}"
    cat >&2 <<EOF
::warning::Input 'kimi-api-key' is deprecated and will be removed in a future release. Migrate to 'api-key' (OpenRouter key).

Migration (recommended):
- uses: misty-step/cerberus@${invoked_ref}
  with:
    api-key: \${{ secrets.OPENROUTER_API_KEY }}

The 'kimi-api-key' alias continues to work for backward compatibility but may be removed in v3.
EOF
  fi
fi
if [[ -z "$resolved_key" ]]; then
  resolved_key="${CERBERUS_API_KEY:-}"
fi
if [[ -z "$resolved_key" ]]; then
  resolved_key="${OPENROUTER_API_KEY:-}"
fi

if [[ -z "$resolved_key" ]]; then
  # Determine invoked version for accurate error message
  invoked_ref="${GITHUB_ACTION_REF:-v2}"
  cat >&2 <<EOF
::error::Missing API key for Cerberus review.
Provide one of:
1) with: api-key  (recommended)
2) with: kimi-api-key  (deprecated alias)
3) env: CERBERUS_API_KEY  (job-level env only)
4) env: OPENROUTER_API_KEY  (job-level env only)

Note: step-level env: does NOT propagate into composite actions.
Use 'with: api-key' or set env at the job level.

Example:
- uses: misty-step/cerberus@${invoked_ref}
  with:
    api-key: \${{ secrets.OPENROUTER_API_KEY }}
EOF
  exit 1
fi

echo "::add-mask::$resolved_key"
echo "OPENROUTER_API_KEY=$resolved_key" >> "$GITHUB_ENV"
