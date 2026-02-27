#!/usr/bin/env bash
set -euo pipefail

# Test matrix generation from config.yml using the shared generate-matrix.py script.

cd "$(dirname "$0")/../.."

SCRIPT="matrix/generate-matrix.py"

# --- Test 1: synthetic config ---
test_config=$(mktemp)
wave_config=""
trap 'rm -f "$test_config" "$wave_config"' EXIT
cat > "$test_config" << 'EOF'
version: 1
council:
  name: "Test Cerberus"
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

# --- Test 1b: model-tier propagation ---
with_tier_output="$(MODEL_TIER=flash python3 "$SCRIPT" "$test_config")"
with_tier_matrix=$(echo "$with_tier_output" | sed -n '1p')

if ! python3 - "$with_tier_matrix" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
missing = [item for item in payload["include"] if item.get("model_tier") != "flash"]
if missing:
    sys.exit(1)
PY
then
    echo "FAIL: matrix entries did not propagate model_tier from MODEL_TIER env"
    exit 1
fi

echo "PASS: Matrix includes propagated model_tier from env"

# --- Test 1c: wave filtering + model_wave propagation ---
wave_config=$(mktemp)
cat > "$wave_config" << 'EOF'
version: 1
waves:
  definitions:
    wave1:
      reviewers: [TEST1]
    wave2:
      reviewers: [TEST2]
reviewers:
  - name: TEST1
    perspective: correctness
  - name: TEST2
    perspective: security
EOF

wave_output="$(REVIEW_WAVE=wave2 MODEL_TIER=standard python3 "$SCRIPT" "$wave_config")"
wave_matrix=$(echo "$wave_output" | sed -n '1p')
wave_count=$(echo "$wave_output" | sed -n '2p')

if [[ "$wave_count" != "1" ]]; then
    echo "FAIL: Expected wave2 matrix count 1, got $wave_count"
    exit 1
fi

if ! python3 - "$wave_matrix" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
entry = payload["include"][0]
if entry.get("reviewer") != "TEST2":
    sys.exit(1)
if entry.get("model_wave") != "wave2":
    sys.exit(1)
if entry.get("wave") != "wave2":
    sys.exit(1)
PY
then
    echo "FAIL: wave-filtered matrix missing expected reviewer/model_wave metadata"
    exit 1
fi

echo "PASS: Wave filtering emits expected matrix metadata"

# --- Test 2: actual defaults/config.yml ---
result=$(python3 "$SCRIPT" "defaults/config.yml")
count=$(echo "$result" | sed -n '2p')

if [[ "$count" != "6" ]]; then
    echo "FAIL: Expected 6 reviewers from defaults/config.yml, got $count"
    exit 1
fi

echo "PASS: Actual config.yml produces 6 reviewers"

# Verify key reviewers present
if ! echo "$result" | grep -q "trace"; then
    echo "FAIL: trace not found in matrix"
    exit 1
fi
if ! echo "$result" | grep -q "proof"; then
    echo "FAIL: proof not found in matrix"
    exit 1
fi

rm -f "$wave_config"

echo "PASS: Matrix contains expected reviewers (trace, proof)"
echo "All matrix tests passed!"
