#!/bin/bash
# Tests for sync-v1-tag.sh

set -euo pipefail

# Test configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_DIR=$(mktemp -d "${TMPDIR:-/tmp}/sync-v1-tag.XXXXXX")
TEST_REPO="$TEST_DIR/repo"
BARE_REMOTE="$TEST_DIR/remote.git"
trap 'rm -rf "$TEST_DIR"' EXIT

# Setup test repo with a bare remote so sync-v1-tag.sh can fetch/push
setup_repo() {
  rm -rf "$TEST_REPO" "$BARE_REMOTE"

  # Create bare remote
  git init --bare "$BARE_REMOTE"

  # Create working repo
  git clone "$BARE_REMOTE" "$TEST_REPO"
  cd "$TEST_REPO"
  git config user.name "Test User"
  git config user.email "test@example.com"

  # Initial commit
  echo "initial" > file.txt
  git add file.txt
  git commit -m "Initial commit"

  # Create v1.0.0
  echo "v1.0.0" > file.txt
  git add file.txt
  git commit -m "Release v1.0.0"
  git tag -a v1.0.0 -m "Version 1.0.0"

  # Create v1.1.0
  echo "v1.1.0" > file.txt
  git add file.txt
  git commit -m "Release v1.1.0"
  git tag -a v1.1.0 -m "Version 1.1.0"

  # Create v2.0.0
  echo "v2.0.0" > file.txt
  git add file.txt
  git commit -m "Release v2.0.0"
  git tag -a v2.0.0 -m "Version 2.0.0"

  # Push everything to bare remote
  git push origin HEAD --tags
}

# Test: Finds latest v1.x.x tag
test_finds_latest_v1_tag() {
  setup_repo

  local latest
  latest=$(git tag -l 'v1.*' | grep -E '^v1\.[0-9]+\.[0-9]+$' | sort -V | tail -1)

  if [[ "$latest" != "v1.1.0" ]]; then
    echo "FAIL: Expected v1.1.0, got $latest"
    return 1
  fi
  echo "PASS: Finds latest v1.x.x tag"
}

# Test: Handles annotated tags correctly
test_annotated_tag_sha() {
  setup_repo

  local commit_sha tag_sha
  commit_sha=$(git rev-parse v1.1.0^{commit})
  tag_sha=$(git rev-parse v1.1.0)

  if [[ "$commit_sha" == "$tag_sha" ]]; then
    echo "FAIL: Annotated tag should have different SHA than commit"
    return 1
  fi

  # Verify we can resolve commit from annotated tag
  local resolved
  resolved=$(git rev-parse -q --verify "v1.1.0^{commit}" 2>/dev/null)
  if [[ "$resolved" != "$commit_sha" ]]; then
    echo "FAIL: Could not resolve commit from annotated tag"
    return 1
  fi
  echo "PASS: Handles annotated tags correctly"
}

# Test: Updates v1 tag when behind
test_updates_v1_tag() {
  setup_repo

  # Set v1 to v1.0.0 commit (behind latest)
  git tag -fa v1 v1.0.0^{commit} -m "Initial v1"
  git push origin "refs/tags/v1" --force

  local before after
  before=$(git rev-parse v1^{commit})

  # Run sync
  bash "$SCRIPT_DIR/../sync-v1-tag.sh"

  after=$(git rev-parse v1^{commit})

  if [[ "$before" == "$after" ]]; then
    echo "FAIL: v1 tag should have been updated"
    return 1
  fi

  if [[ "$after" != "$(git rev-parse v1.1.0^{commit})" ]]; then
    echo "FAIL: v1 should point to v1.1.0 commit"
    return 1
  fi
  echo "PASS: Updates v1 tag when behind"
}

# Test: Skips when v1 is current
test_skips_when_current() {
  setup_repo

  # Set v1 to latest v1.x.x
  git tag -fa v1 v1.1.0^{commit} -m "Current v1"
  git push origin "refs/tags/v1" --force

  # Run sync - should exit 0 without changes
  if ! bash "$SCRIPT_DIR/../sync-v1-tag.sh" 2>&1 | grep -q "already points"; then
    echo "FAIL: Should report v1 is already up to date"
    return 1
  fi
  echo "PASS: Skips when v1 is current"
}

# Run tests
echo "Running sync-v1-tag.sh tests..."
test_finds_latest_v1_tag
test_annotated_tag_sha
test_updates_v1_tag
test_skips_when_current
echo "All tests passed!"
