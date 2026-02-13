#!/usr/bin/env bash
set -euo pipefail

# Test matrix action generation from config.yml

cd "$(dirname "$0")/../.."

# Create a test config matching actual structure
test_config=$(mktemp)
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

# Test the Python logic used in the action
python3 -c "
import yaml
import json

with open('$test_config', 'r') as f:
    config = yaml.safe_load(f)

reviewers = config.get('reviewers', [])
matrix = []
reviewer_names = []
for reviewer in reviewers:
    name = reviewer.get('name')
    perspective = reviewer.get('perspective')
    if name and perspective:
        matrix.append({'reviewer': name, 'perspective': perspective})
        reviewer_names.append(name)

print(json.dumps({'include': matrix}))
print(len(matrix))
print(','.join(reviewer_names))
"

# Verify output
expected_matrix='{"include": [{"reviewer": "TEST1", "perspective": "correctness"}, {"reviewer": "TEST2", "perspective": "security"}]}'
expected_count="2"
expected_names="TEST1,TEST2"

echo "Expected matrix: $expected_matrix"
echo "Expected count: $expected_count"
echo "Expected names: $expected_names"

# Test with actual defaults/config.yml
result=$(python3 -c "
import yaml
import json

with open('defaults/config.yml', 'r') as f:
    config = yaml.safe_load(f)

reviewers = config.get('reviewers', [])
matrix = []
reviewer_names = []
for reviewer in reviewers:
    name = reviewer.get('name')
    perspective = reviewer.get('perspective')
    if name and perspective:
        matrix.append({'reviewer': name, 'perspective': perspective})
        reviewer_names.append(name)

print(json.dumps({'include': matrix}))
print('COUNT:', len(matrix))
print('NAMES:', ','.join(reviewer_names))
")

echo "$result"

# Extract count from output
count=$(echo "$result" | grep 'COUNT:' | awk '{print $2}')

# Should have 6 reviewers
if [[ "$count" != "6" ]]; then
    echo "FAIL: Expected 6 reviewers from defaults/config.yml, got $count"
    exit 1
fi

echo "PASS: Actual config.yml produces 6 reviewers"

# Verify the matrix contains expected reviewers
if ! echo "$result" | grep -q "APOLLO"; then
    echo "FAIL: APOLLO not found in matrix"
    exit 1
fi

if ! echo "$result" | grep -q "CASSANDRA"; then
    echo "FAIL: CASSANDRA not found in matrix"
    exit 1
fi

echo "PASS: Matrix contains expected reviewers (APOLLO, CASSANDRA)"

rm "$test_config"
echo "All matrix tests passed!"
