#!/usr/bin/env bash
set -euo pipefail

# Test matrix generation from config.yml using the shared generate-matrix.py script.

cd "$(dirname "$0")/../.."

SCRIPT="matrix/generate-matrix.py"

# --- Test 1: synthetic config ---
test_config=$(mktemp)
trap 'rm -f "$test_config"' EXIT
cat > "$test_config" << 'EOF'
version: 1
council:
  name: "Test Council"
reviewers:
  - name: TEST1
    perspective: correctness
  - name: TEST2
    perspective: security
EOF

actual_output=$(python3 "$SCRIPT" "$test_config")
actual_matrix=$(echo "$actual_output" | sed -n '1p')
actual_count=$(echo "$actual_output" | sed -n '2p')
actual_names=$(echo "$actual_output" | sed -n '3p')

expected_matrix='{"include": [{"reviewer": "TEST1", "perspective": "correctness", "reviewer_label": "Correctness", "reviewer_codename": "Test1"}, {"reviewer": "TEST2", "perspective": "security", "reviewer_label": "Security", "reviewer_codename": "Test2"}]}'
expected_count="2"
expected_names="TEST1,TEST2"

if [[ "$actual_matrix" != "$expected_matrix" ]]; then
    echo "FAIL: Matrix mismatch"
    echo "  Expected: $expected_matrix"
    echo "  Actual:   $actual_matrix"
    exit 1
fi
if [[ "$actual_count" != "$expected_count" ]]; then
    echo "FAIL: Count mismatch — expected $expected_count, got $actual_count"
    exit 1
fi
if [[ "$actual_names" != "$expected_names" ]]; then
    echo "FAIL: Names mismatch — expected $expected_names, got $actual_names"
    exit 1
fi

echo "PASS: Synthetic config produces correct matrix"

# --- Test 2: actual defaults/config.yml ---
result=$(python3 "$SCRIPT" "defaults/config.yml")
count=$(echo "$result" | sed -n '2p')

if [[ "$count" != "12" ]]; then
    echo "FAIL: Expected 12 reviewers from defaults/config.yml, got $count"
    exit 1
fi

echo "PASS: Actual config.yml produces 12 reviewers"

# Verify key reviewers present
if ! echo "$result" | grep -q "trace"; then
    echo "FAIL: trace not found in matrix"
    exit 1
fi
if ! echo "$result" | grep -q "proof"; then
    echo "FAIL: proof not found in matrix"
    exit 1
fi

echo "PASS: Matrix contains expected reviewers (trace, proof)"
echo "All matrix tests passed!"
