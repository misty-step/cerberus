#!/usr/bin/env bash
set -euo pipefail

resolved_key="${INPUT_KIMI_API_KEY:-}"
if [[ -z "$resolved_key" ]]; then
  resolved_key="${CERBERUS_API_KEY:-}"
fi
if [[ -z "$resolved_key" ]]; then
  resolved_key="${ANTHROPIC_API_KEY:-}"
fi

if [[ -z "$resolved_key" ]]; then
  cat >&2 <<'EOF'
::error::Missing API key for Cerberus review.
Provide one of:
1) with: kimi-api-key  (recommended)
2) env: CERBERUS_API_KEY  (job-level env only)
3) env: ANTHROPIC_API_KEY  (job-level env only)

Note: step-level env: does NOT propagate into composite actions.
Use 'with: kimi-api-key' or set env at the job level.

Example:
- uses: misty-step/cerberus@v1
  with:
    kimi-api-key: ${{ secrets.CERBERUS_API_KEY }}
EOF
  exit 1
fi

echo "::add-mask::$resolved_key"
echo "KIMI_API_KEY=$resolved_key" >> "$GITHUB_ENV"
