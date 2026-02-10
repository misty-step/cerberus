#!/bin/bash
# Sync v1 floating tag to latest v1.x.x release
# Addresses Council feedback: consistent triggers, test coverage, annotated tag handling

set -euo pipefail

# Configuration
V1_TAG="v1"
V1_PATTERN='^v1\.[0-9]+\.[0-9]+$'

# Fetch all tags
git fetch origin --tags --force

# Get the latest v1.x.x tag by version sort
latest_v1_tag=$(git tag -l 'v1.*' | grep -E "$V1_PATTERN" | sort -V | tail -1)

if [[ -z "$latest_v1_tag" ]]; then
  echo "No v1.x.x tags found"
  exit 0
fi

# Get commit SHA for the latest v1.x.x tag (handles annotated tags)
target_sha=$(git rev-parse -q --verify "${latest_v1_tag}^{commit}" 2>/dev/null || git rev-list -n1 "$latest_v1_tag")

# Get commit SHA for current v1 tag (handles annotated tags)
current_tag_sha=$(git rev-parse -q --verify "refs/tags/${V1_TAG}^{commit}" 2>/dev/null || git rev-parse -q --verify "refs/tags/${V1_TAG}" 2>/dev/null || true)

# Compare commit SHAs
if [[ "$current_tag_sha" == "$target_sha" ]]; then
  echo "v1 already points to ${target_sha} (${latest_v1_tag})"
  exit 0
fi

echo "Updating v1 tag from ${current_tag_sha:-none} to ${target_sha} (${latest_v1_tag})"

# Configure git
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

# Update tag
git tag -fa "$V1_TAG" "$target_sha" -m "Move v1 to ${latest_v1_tag} (${target_sha})"
git push origin "refs/tags/${V1_TAG}" --force
