#!/usr/bin/env bash
# Regression test for issue #51: Argument list too long on large PR diffs.
#
# Verifies that run-reviewer.sh passes the prompt via stdin (not as a
# command-line argument), avoiding ARG_MAX limits on diffs >2 MB.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- helpers ---
pass() { printf "  PASS: %s\n" "$1"; }
fail() { printf "  FAIL: %s\n" "$1"; FAILURES=$((FAILURES + 1)); }
FAILURES=0

echo "=== test_large_diff ==="

# --- 1. Verify no --prompt "$(cat" pattern in run-reviewer.sh ---
echo "  checking: no --prompt \"\$(cat\" in run-reviewer.sh"
if grep -q -- '--prompt "$(cat' "$REPO_ROOT/scripts/run-reviewer.sh"; then
  fail "run-reviewer.sh still uses --prompt with command substitution"
else
  pass "prompt passed via stdin, not command-line argument"
fi

# --- 2. Verify stdin redirect is present for the kimi invocation ---
echo "  checking: stdin redirect from prompt file"
if grep -qE '< "/tmp/\$\{perspective\}-review-prompt\.md"' "$REPO_ROOT/scripts/run-reviewer.sh"; then
  pass "kimi invocation reads prompt from stdin via file redirect"
else
  fail "expected stdin redirect from review-prompt.md not found"
fi

# --- 3. Verify GH_DIFF_FILE path is used by action.yml (not GH_DIFF env) ---
echo "  checking: action.yml uses GH_DIFF_FILE, not GH_DIFF env"
if grep -q 'GH_DIFF_FILE:' "$REPO_ROOT/action.yml"; then
  pass "action.yml passes diff as file path"
else
  fail "action.yml should use GH_DIFF_FILE"
fi

# --- 4. Generate large prompt file and verify it fits in a file (sanity) ---
echo "  checking: large prompt file round-trip"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

# Generate a 3 MB prompt (larger than typical ARG_MAX of 2 MB)
python3 -c "
import os, sys
line = 'diff --git a/big.py b/big.py\n+' + 'x' * 200 + '\n'
target = 3 * 1024 * 1024  # 3 MB
with open(os.path.join(sys.argv[1], 'big-prompt.md'), 'w') as f:
    written = 0
    while written < target:
        f.write(line)
        written += len(line)
" "$tmpdir"

size=$(wc -c < "$tmpdir/big-prompt.md")
if [[ "$size" -gt 2000000 ]]; then
  pass "generated ${size}-byte prompt file (exceeds ARG_MAX)"
else
  fail "prompt file too small: ${size} bytes"
fi

# --- summary ---
echo ""
if [[ "$FAILURES" -eq 0 ]]; then
  echo "All tests passed."
  exit 0
else
  echo "${FAILURES} test(s) failed."
  exit 1
fi
