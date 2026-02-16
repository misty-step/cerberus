#!/usr/bin/env bash
set -euo pipefail

# Validate that templates/consumer-workflow.yml matches defaults/config.yml
# This catches drift between the hardcoded template and the actual reviewer roster.

# Find repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

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

# Extract reviewers from consumer-workflow.yml
template_reviewers=$(grep -A 20 'matrix:' templates/consumer-workflow.yml | \
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
    echo "ERROR: templates/consumer-workflow.yml does not match defaults/config.yml"
    echo ""
    echo "The hardcoded reviewer matrix in the template has drifted from the actual roster."
    echo "Either:"
    echo "  1. Update templates/consumer-workflow.yml to match defaults/config.yml, or"
    echo "  2. Switch to templates/consumer-workflow-minimal.yml which stays in sync automatically"
    exit 1
fi

echo ""
echo "PASS: Template matches config"
