#!/usr/bin/env bash
set -euo pipefail

# Validate that templates/consumer-workflow-reusable.yml matches defaults/config.yml
# This catches drift between the hardcoded template and the actual reviewer roster.

# Find repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

# If consumer-workflow-reusable.yml delegates to the reusable workflow, skip matrix parity.
# The matrix is centralized in .github/workflows/cerberus.yml — drift is impossible by design.
if grep -q "uses: misty-step/cerberus/.github/workflows/cerberus.yml" templates/consumer-workflow-reusable.yml; then
  echo "consumer-workflow-reusable.yml uses reusable workflow — matrix parity check not applicable"
  exit 0
fi

# Extract reviewers from config.yml
config_reviewers=$(python3 -c "
import yaml
import json

with open('defaults/config.yml', 'r') as f:
    config = yaml.safe_load(f)

reviewers = config.get('reviewers', [])
result = []
for r in reviewers:
    name = r.get('name', '')
    perspective = r.get('perspective', '')
    if name and perspective:
        result.append(f'{name}:{perspective}')
print(','.join(sorted(result)))
")

# Extract reviewers from consumer-workflow-reusable.yml
template_reviewers=$(grep -A 20 'matrix:' templates/consumer-workflow-reusable.yml | \
    grep -E '^\s+- \{ reviewer:' | \
    sed -E 's/.*reviewer: ([^,}]+).*perspective: ([^,}]+).*/\1:\2/' | \
    sed 's/[[:space:]]*$//' | \
    sort | \
    tr '\n' ',' | \
    sed 's/,$//')

echo "Config reviewers:    $config_reviewers"
echo "Template reviewers:  $template_reviewers"

if [[ "$config_reviewers" != "$template_reviewers" ]]; then
    echo ""
    echo "ERROR: templates/consumer-workflow-reusable.yml does not match defaults/config.yml"
    echo ""
    echo "The hardcoded reviewer matrix in the template has drifted from the actual roster."
    echo "Either:"
    echo "  1. Update templates/consumer-workflow-reusable.yml to match defaults/config.yml, or"
    echo "  2. Switch to templates/consumer-workflow-minimal.yml which stays in sync automatically"
    exit 1
fi

echo ""
echo "PASS: Template matches config"
