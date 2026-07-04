#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

grep -q 'misty-step/landmark@v1' .github/workflows/release.yml
if grep -q '"@semantic-release/git"' .releaserc.json; then
  echo ".releaserc.json must not use @semantic-release/git; protected master rejects release commits" >&2
  exit 1
fi
if grep -q '"@semantic-release/changelog"' .releaserc.json; then
  echo ".releaserc.json must not generate CHANGELOG.md during release; releases are GitHub-release only" >&2
  exit 1
fi

cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --locked

# Backlog 010: secret-scan the working tree before publication. Gated on
# gitleaks being installed (skipped, not failed, when it isn't — CI always
# has it; a cold agent's local machine may not). No allowlist mechanism for
# an individual finding today: a true positive must be removed, not
# suppressed. .gitleaks.toml excludes only target/ (build output).
if command -v gitleaks > /dev/null 2>&1; then
  gitleaks detect --no-git --source . --no-banner
else
  echo "gitleaks not installed; skipping secret scan (CI always has it)" >&2
fi

cargo run --locked -- review --help > target/cerberus-review-help.txt
grep -q '\[default: opencode\]' target/cerberus-review-help.txt
grep -q 'possible values: opencode, omp, fixture, container-opencode' target/cerberus-review-help.txt
grep -q -- '--receipt-bundle' target/cerberus-review-help.txt
grep -q -- '--producer-manifest' target/cerberus-review-help.txt
grep -q -- '--openrouter-scoped-key' target/cerberus-review-help.txt
grep -q -- '--openrouter-provisioning-key-file' target/cerberus-review-help.txt
grep -q -- '--openrouter-provisioning-key-env' target/cerberus-review-help.txt
grep -q -- '--openrouter-key-limit-usd' target/cerberus-review-help.txt
grep -q -- '--docker-binary' target/cerberus-review-help.txt
grep -q -- '--container-image' target/cerberus-review-help.txt
grep -q -- '--container-binary' target/cerberus-review-help.txt
grep -q -- '--container-host-root' target/cerberus-review-help.txt
grep -q -- '--container-egress-allow-host' target/cerberus-review-help.txt
grep -q -- '--container-orphan-sweep-seconds' target/cerberus-review-help.txt
cargo run --locked -- request --help > target/cerberus-request-help.txt
grep -q 'git-range' target/cerberus-request-help.txt
grep -Eq '^  pr([[:space:]]|$)' target/cerberus-request-help.txt
cargo run --locked -- request git-range --help > target/cerberus-request-git-range-help.txt
grep -q -- '--base-workspace' target/cerberus-request-git-range-help.txt
grep -q -- '--local-runtime-command' target/cerberus-request-git-range-help.txt
grep -q -- '--allow-local-runtime' target/cerberus-request-git-range-help.txt
cargo run --locked -- request pr --help > target/cerberus-request-pr-help.txt
grep -q -- '--base-workspace' target/cerberus-request-pr-help.txt
cargo run --locked -- review-pr --help > target/cerberus-review-pr-help.txt
grep -q -- '--dry-run' target/cerberus-review-pr-help.txt
grep -q -- '--post' target/cerberus-review-pr-help.txt
grep -q -- '--summary-target' target/cerberus-review-pr-help.txt
grep -q -- '--receipt-bundle' target/cerberus-review-pr-help.txt
grep -q -- '--gh-token-file' target/cerberus-review-pr-help.txt
grep -q -- '--gh-token-env' target/cerberus-review-pr-help.txt
grep -q -- '--remote-event' target/cerberus-review-pr-help.txt
grep -q -- '--openrouter-scoped-key' target/cerberus-review-pr-help.txt
cargo run --locked -- mcp --help > target/cerberus-mcp-help.txt
grep -q 'Run the Cerberus MCP server over stdio' target/cerberus-mcp-help.txt

rm -rf target/cerberus
mkdir -p target/cerberus
mkdir -p target/cerberus/receipts

expect_review_failure() {
  local name="$1"
  local fixture="$2"

  if cargo run --locked -- review \
    --request fixtures/requests/diff-only.json \
    --harness fixture \
    --fixture-output "$fixture" \
    --out "target/cerberus/${name}-artifact.json" \
    --execution-plan "target/cerberus/${name}-execution_plan.json" \
    --transcript "target/cerberus/${name}-transcript.txt" \
    > "target/cerberus/${name}.stdout" \
    2> "target/cerberus/${name}.stderr"; then
    echo "expected fixture review to fail: ${name}" >&2
    exit 1
  fi
}

# The agent now emits one artifact file, so the old marker/XML/raw "duplicate
# candidate" cases no longer have a parser to defeat — a file holds exactly one
# artifact. The meaningful adversarial floor is the validator: an emission that
# parses but overstates context or dangles a reference must still be rejected.
# Fixtures are bare ReviewArtifact.v1 JSON templates; the fixture substrate
# writes them to the out-path and reads them back, then validation runs.
sed 's#{{context_capabilities}}#{"diff":true,"repo_head":false,"repo_base":true,"local_runtime":false,"remote_runtime":false,"external_research":"forbid"}#' \
  fixtures/harness/pass-review.txt \
  > target/cerberus/invalid-overstated-base.txt
sed 's#{{context_capabilities}}#{"diff":true,"repo_head":false,"repo_base":false,"local_runtime":true,"remote_runtime":false,"external_research":"forbid"}#' \
  fixtures/harness/pass-review.txt \
  > target/cerberus/invalid-overstated-runtime.txt
expect_review_failure overstated-base target/cerberus/invalid-overstated-base.txt
expect_review_failure overstated-runtime target/cerberus/invalid-overstated-runtime.txt
expect_review_failure unknown-finding-id fixtures/harness/invalid-unknown-finding-id.txt
expect_review_failure unknown-suggested-fix fixtures/harness/invalid-unknown-suggested-fix.txt
expect_review_failure orphan-suggested-fix fixtures/harness/invalid-orphan-suggested-fix.txt

grep -q 'artifact context capabilities overstate the request' target/cerberus/overstated-base.stderr
grep -q 'artifact context capabilities overstate the request' target/cerberus/overstated-runtime.stderr
grep -q 'references unknown finding id' target/cerberus/unknown-finding-id.stderr
grep -q 'references unknown suggested fix id' target/cerberus/unknown-suggested-fix.stderr
grep -q 'top-level suggested fix is not attached' target/cerberus/orphan-suggested-fix.stderr

# THE re-ask test (Oracle #1): the fake agent writes an INVALID artifact (wrong
# request digest) on its first emission, then a VALID one when the harness
# continues its OpenCode session. The review must succeed only via the re-ask,
# and the transcript must show the exact validation error carried back.
GH_TOKEN=should-not-leak CERBERUS_FAKE_OPENCODE_FIRST_INVALID=1 cargo run --locked -- review \
  --request fixtures/requests/diff-only-reask.json \
  --harness opencode \
  --opencode-binary "$PWD/fixtures/bin/fake-opencode" \
  --out target/cerberus/reask-artifact.json \
  --execution-plan target/cerberus/reask-execution_plan.json \
  --transcript target/cerberus/reask-transcript.txt \
  --receipt-bundle target/cerberus/receipts/reask.json

test -s target/cerberus/reask-artifact.json
grep -q '"trusted_for_posting": true' target/cerberus/receipts/reask.json
grep -q '\[attempt: re-ask\]' target/cerberus/reask-transcript.txt
grep -q 'artifact request digest mismatch' target/cerberus/reask-transcript.txt
# The recovered artifact carries the correct digest, not the deliberately-wrong one.
if grep -q 'sha256:0000000000000000000000000000000000000000000000000000000000000000' \
  target/cerberus/reask-artifact.json; then
  echo "re-ask accepted the invalid first emission" >&2
  exit 1
fi

cat > target/cerberus/fake-opencode-old <<'SH'
#!/usr/bin/env sh
if [ "${1:-}" = "--version" ]; then
  printf '%s\n' "0.0.0"
  exit 0
fi
exec "$CERBERUS_FAKE_OPENCODE" "$@"
SH
chmod +x target/cerberus/fake-opencode-old
if CERBERUS_FAKE_OPENCODE="$PWD/fixtures/bin/fake-opencode" cargo run --locked -- review \
  --request fixtures/requests/diff-only.json \
  --harness opencode \
  --opencode-binary "$PWD/target/cerberus/fake-opencode-old" \
  --out target/cerberus/opencode-version-drift-artifact.json \
  > target/cerberus/opencode-version-drift.stdout \
  2> target/cerberus/opencode-version-drift.stderr; then
  echo "expected OpenCode version drift to fail before review execution" >&2
  exit 1
fi
grep -q 'OpenCode version drift' target/cerberus/opencode-version-drift.stderr
grep -q 'config/opencode-version.json' target/cerberus/opencode-version-drift.stderr
grep -q 'docs/opencode-substrate.md#bumping-the-opencode-pin' \
  target/cerberus/opencode-version-drift.stderr

if CERBERUS_FAKE_OPENCODE_TIMEOUT=1 CERBERUS_FAKE_OPENCODE_TIMEOUT_SECONDS=3 cargo run --locked -- review \
  --request fixtures/requests/diff-only.json \
  --harness opencode \
  --opencode-binary "$PWD/fixtures/bin/fake-opencode" \
  --allow-env CERBERUS_FAKE_OPENCODE_TIMEOUT \
  --allow-env CERBERUS_FAKE_OPENCODE_TIMEOUT_SECONDS \
  --timeout-seconds 1 \
  --out target/cerberus/timeout-no-reask-artifact.json \
  --transcript target/cerberus/timeout-no-reask-transcript.txt \
  > target/cerberus/timeout-no-reask.stdout \
  2> target/cerberus/timeout-no-reask.stderr; then
  echo "expected timed-out opencode review to fail without a re-ask" >&2
  exit 1
fi
grep -q 'harness timed out after' target/cerberus/timeout-no-reask.stderr
grep -q '\[attempt: initial\]' target/cerberus/timeout-no-reask-transcript.txt
if grep -q '\[attempt: re-ask\]' target/cerberus/timeout-no-reask-transcript.txt; then
  echo "timed-out opencode attempt should not launch a re-ask" >&2
  exit 1
fi

# Backlog 013 M1: --openrouter-scoped-key must refuse to mint without an
# explicit provisioning-key source — no ambient-env fallback, same house
# pattern as --gh-token-file/--gh-token-env. These fail before any network
# call, so they run unconditionally (no provisioning key needed).
if cargo run --locked -- review \
  --request fixtures/requests/diff-only.json \
  --harness fixture \
  --fixture-output fixtures/harness/valid-review.txt \
  --out target/cerberus/scoped-key-no-source-artifact.json \
  --openrouter-scoped-key \
  > target/cerberus/scoped-key-no-source.stdout \
  2> target/cerberus/scoped-key-no-source.stderr; then
  echo "expected --openrouter-scoped-key without an explicit provisioning-key source to fail" >&2
  exit 1
fi
grep -q 'requires an explicit provisioning key' target/cerberus/scoped-key-no-source.stderr

if cargo run --locked -- review \
  --request fixtures/requests/diff-only.json \
  --harness fixture \
  --fixture-output fixtures/harness/valid-review.txt \
  --out target/cerberus/scoped-key-both-sources-artifact.json \
  --openrouter-scoped-key \
  --openrouter-provisioning-key-file target/cerberus/nonexistent-provisioning-key.txt \
  --openrouter-provisioning-key-env CERBERUS_UNUSED_OPENROUTER_PROVISIONING_KEY \
  > target/cerberus/scoped-key-both-sources.stdout \
  2> target/cerberus/scoped-key-both-sources.stderr; then
  echo "expected --openrouter-scoped-key with both key sources to fail" >&2
  exit 1
fi
grep -q 'exactly one explicit' target/cerberus/scoped-key-both-sources.stderr

printf 'stale receipt should be removed before a failed run\n' \
  > target/cerberus/receipts/stale-before-failed-review.json
printf 'no review artifact here\n' > target/cerberus/no-artifact.txt
if cargo run --locked -- review \
  --request fixtures/requests/diff-only.json \
  --harness fixture \
  --fixture-output target/cerberus/no-artifact.txt \
  --out target/cerberus/no-artifact-output.json \
  --receipt-bundle target/cerberus/receipts/stale-before-failed-review.json \
  > target/cerberus/no-artifact.stdout \
  2> target/cerberus/no-artifact.stderr; then
  echo "expected missing artifact review to fail" >&2
  exit 1
fi
test ! -e target/cerberus/receipts/stale-before-failed-review.json

python3 - <<'PY'
from pathlib import Path

source = Path("fixtures/harness/valid-review.txt")
target = Path("target/cerberus/invalid-secret-schema.txt")
text = source.read_text()
text = text.replace(
    '"schema_version": "cerberus.review_artifact.v1"',
    '"schema_version": "cerberus.review_artifact.v1 GH_TOKEN master-prompt.md review-request.json"',
    1,
)
target.write_text(text)
PY
if cargo run --locked -- review \
  --request fixtures/requests/diff-only.json \
  --harness fixture \
  --fixture-output target/cerberus/invalid-secret-schema.txt \
  --out target/cerberus/invalid-secret-schema-artifact.json \
  --execution-plan target/cerberus/invalid-secret-schema-execution_plan.json \
  --transcript target/cerberus/invalid-secret-schema-transcript.txt \
  --receipt-bundle target/cerberus/receipts/invalid-secret-schema.json \
  > target/cerberus/invalid-secret-schema.stdout \
  2> target/cerberus/invalid-secret-schema.stderr; then
  echo "expected invalid schema review to fail" >&2
  exit 1
fi
test -s target/cerberus/invalid-secret-schema-artifact.json
test -s target/cerberus/receipts/invalid-secret-schema.json
grep -q '"status": "failed"' target/cerberus/receipts/invalid-secret-schema.json
grep -q '"trusted_for_posting": false' target/cerberus/receipts/invalid-secret-schema.json
grep -q '"error": "artifact_validation_failed"' target/cerberus/receipts/invalid-secret-schema.json
if grep -q 'GH_TOKEN\|master-prompt.md\|review-request.json' \
  target/cerberus/receipts/invalid-secret-schema.json; then
  echo "failed-validation receipt leaked private validation details" >&2
  exit 1
fi
python3 - <<'PY'
import hashlib
import json
from pathlib import Path

artifact = Path("target/cerberus/invalid-secret-schema-artifact.json").read_bytes()
receipt = json.loads(Path("target/cerberus/receipts/invalid-secret-schema.json").read_text())
expected = "sha256:" + hashlib.sha256(artifact).hexdigest()
if receipt["artifact_digest"] != expected:
    raise SystemExit(f"artifact digest mismatch: {receipt['artifact_digest']} != {expected}")
PY

tmp_repo="$(mktemp -d)"
trap 'rm -rf "$tmp_repo"' EXIT
git -C "$tmp_repo" init -q
git -C "$tmp_repo" config user.email "cerberus@example.invalid"
git -C "$tmp_repo" config user.name "Cerberus Test"
mkdir -p "$tmp_repo/src"
cat > "$tmp_repo/src/ratio.rs" <<'RATIO'
pub fn ratio(numerator: f64, denominator: f64) -> f64 {
    numerator / denominator
}
RATIO
git -C "$tmp_repo" add src/ratio.rs
git -C "$tmp_repo" commit -q -m "base"
base_sha="$(git -C "$tmp_repo" rev-parse HEAD)"
cat > "$tmp_repo/src/ratio.rs" <<'RATIO'
pub fn ratio(numerator: f64, denominator: f64) -> f64 {
    if denominator == 0.0 {
        return 0.0;
    }
    numerator / denominator
}
RATIO
git -C "$tmp_repo" add src/ratio.rs
git -C "$tmp_repo" commit -q -m "guard denominator"
head_sha="$(git -C "$tmp_repo" rev-parse HEAD)"

mkdir -p target/cerberus/context-tiers

cargo run --locked -- request git-range \
  --repo-path "$tmp_repo" \
  --base "$base_sha" \
  --head "$head_sha" \
  --instruction "Exercise generated git-range request review." \
  --out target/cerberus/git-range-request.json

grep -q '"kind": "git_range"' target/cerberus/git-range-request.json
grep -q '"base"' target/cerberus/git-range-request.json
cargo run --locked -- review \
  --request target/cerberus/git-range-request.json \
  --harness fixture \
  --fixture-output fixtures/harness/valid-review.txt \
  --out target/cerberus/git-range-artifact.json \
  --markdown target/cerberus/git-range-review.md \
  --execution-plan target/cerberus/git-range-execution_plan.json \
  --receipt-bundle target/cerberus/receipts/git-range-fixture.json

GH_TOKEN=should-not-leak cargo run --locked -- review \
  --request target/cerberus/git-range-request.json \
  --harness opencode \
  --opencode-binary "$PWD/fixtures/bin/fake-opencode" \
  --out target/cerberus/git-range-opencode-artifact.json \
  --markdown target/cerberus/git-range-opencode-review.md \
  --execution-plan target/cerberus/git-range-opencode-execution_plan.json \
  --transcript target/cerberus/git-range-opencode-transcript.txt \
  --receipt-bundle target/cerberus/receipts/git-range-opencode.json

producer_dir="target/cerberus/crucible-producer"
mkdir -p "$producer_dir"
cargo run --locked -- request git-range \
  --repo-path "$tmp_repo" \
  --base "$base_sha" \
  --head "$head_sha" \
  --instruction "Produce a Crucible-gradeable Cerberus packet." \
  --out "$producer_dir/request.json"

GH_TOKEN=should-not-leak cargo run --locked -- review \
  --request "$producer_dir/request.json" \
  --harness opencode \
  --opencode-binary "$PWD/fixtures/bin/fake-opencode" \
  --out "$producer_dir/artifact.json" \
  --execution-plan "$producer_dir/execution_plan.json" \
  --transcript "$producer_dir/transcript.txt" \
  --receipt-bundle "$producer_dir/receipt-bundle.json" \
  --producer-manifest "$producer_dir/producer-manifest.json"

if cargo run --locked -- review \
  --request "$producer_dir/request.json" \
  --harness fixture \
  --fixture-output fixtures/harness/valid-review.txt \
  --out "$producer_dir/no-receipt-artifact.json" \
  --producer-manifest "$producer_dir/stale-producer-manifest.json" \
  > "$producer_dir/no-receipt.stdout" \
  2> "$producer_dir/no-receipt.stderr"; then
  echo "expected --producer-manifest without --receipt-bundle to fail" >&2
  exit 1
fi
grep -q -- '--producer-manifest requires --receipt-bundle' "$producer_dir/no-receipt.stderr"
test ! -e "$producer_dir/stale-producer-manifest.json"

python3 - <<'PY'
import json
from pathlib import Path

root = Path("target/cerberus/crucible-producer")
artifact = json.loads((root / "artifact.json").read_text())
receipt = json.loads((root / "receipt-bundle.json").read_text())
manifest = json.loads((root / "producer-manifest.json").read_text())

assert artifact["schema_version"] == "cerberus.review_artifact.v1"
assert isinstance(artifact["findings"], list)
for finding in artifact["findings"]:
    assert finding["id"].strip()
    assert finding["category"].strip()
    assert 0.0 <= finding["confidence"] <= 1.0
    assert finding["title"].strip() or finding["description"].strip()

assert receipt["schema_version"] == "cerberus.review_receipt_bundle.v1"
assert receipt["validation"]["status"] == "passed"
assert receipt["validation"]["trusted_for_posting"] is True
assert receipt["artifact_uri"] == str(root / "artifact.json")

assert manifest["schema_version"] == "cerberus.crucible_producer_manifest.v1"
assert manifest["consumer"] == "crucible"
assert manifest["artifact"]["schema_version"] == artifact["schema_version"]
assert manifest["artifact"]["artifact_digest"] == receipt["artifact_digest"]
assert manifest["artifact"]["finding_count"] == len(artifact["findings"])
assert manifest["receipt_bundle"]["schema_version"] == receipt["schema_version"]
assert manifest["grader_input"]["format"] == "cerberus.review_artifact.v1"
assert manifest["grader_input"]["artifact_uri"] == str(root / "artifact.json")
assert manifest["grader_input"]["findings_path"] == "findings"
assert manifest["grader_input"]["finding_id_path"] == "findings[].id"
assert manifest["validation"]["status"] == "passed"
assert manifest["validation"]["trusted_for_grading"] is True
assert manifest["boundary"]["scorer_owner"] == "crucible"
assert manifest["boundary"]["includes_score"] is False

for path in [root / "receipt-bundle.json", root / "producer-manifest.json"]:
    text = path.read_text()
    for forbidden in ["GH_TOKEN", "should-not-leak", "master-prompt.md", "review-request.json"]:
        if forbidden in text:
            raise SystemExit(f"{path} leaked {forbidden}")
PY

test "$(git -C "$tmp_repo" rev-parse HEAD)" = "$head_sha"

# --- 018: agent-native review-diff exit-code matrix --------------------------
# review-diff fuses request + review locally (no GitHub, no token), prints the
# review to stdout, and gates the exit code on the verdict via --fail-on:
#   0 clean/proceed | 1 blocking verdict | 2 Cerberus error (no valid artifact).
sed 's/"verdict": "WARN"/"verdict": "FAIL"/' fixtures/harness/valid-review.txt \
  > target/cerberus/review-diff-fail-fixture.txt
printf 'not a review artifact\n' > target/cerberus/review-diff-invalid-fixture.txt

expect_exit() {
  local want="$1" name="$2"
  shift 2
  local rc=0
  "$@" > "target/cerberus/review-diff-${name}.stdout" \
    2> "target/cerberus/review-diff-${name}.stderr" || rc=$?
  if [ "$rc" -ne "$want" ]; then
    echo "review-diff exit-code: ${name} wanted ${want}, got ${rc}" >&2
    exit 1
  fi
}

rd() {
  cargo run --locked -- review-diff \
    --repo-path "$tmp_repo" --base "$base_sha" --head "$head_sha" \
    --harness fixture --fixture-output "$1" "${@:2}"
}

# WARN fixture (valid-review.txt): below 'fail' threshold => 0; at 'warn' => 1.
expect_exit 0 warn-failon-fail rd fixtures/harness/valid-review.txt --fail-on fail
expect_exit 1 warn-failon-warn rd fixtures/harness/valid-review.txt --fail-on warn
# FAIL fixture: blocking under 'fail' => 1; default (no --fail-on) => 0 (back-compat).
expect_exit 1 fail-failon-fail rd target/cerberus/review-diff-fail-fixture.txt --fail-on fail
expect_exit 0 fail-default rd target/cerberus/review-diff-fail-fixture.txt
# Unparseable emission: a Cerberus error, not a verdict => 2 (distinct from blocking).
expect_exit 2 invalid rd target/cerberus/review-diff-invalid-fixture.txt --fail-on fail
# stdout carries the rendered review (Markdown), not logs.
grep -q 'Cerberus Review:' target/cerberus/review-diff-warn-failon-fail.stdout
# --fail-on also gates plain `review`, and a blocking verdict is exit 1 there too.
expect_exit 1 review-failon-fail cargo run --locked -- review \
  --request target/cerberus/git-range-request.json \
  --harness fixture --fixture-output target/cerberus/review-diff-fail-fixture.txt \
  --out target/cerberus/review-failon-artifact.json --fail-on fail

mcp_init='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25"}}'
mcp_tools='{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
mcp_review="$(printf '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"review_git_range","arguments":{"repo_path":"%s","base":"%s","head":"%s","harness":"fixture","fixture_output":"fixtures/harness/valid-review.txt","fail_on":"fail"}}}' "$tmp_repo" "$base_sha" "$head_sha")"
printf '%s\n%s\n%s\n' "$mcp_init" "$mcp_tools" "$mcp_review" \
  | cargo run --quiet --locked -- mcp \
  > target/cerberus/mcp.stdout \
  2> target/cerberus/mcp.stderr
grep -q '"protocolVersion":"2025-11-25"' target/cerberus/mcp.stdout
grep -q '"name":"review_git_range"' target/cerberus/mcp.stdout
grep -q 'Cerberus Review:' target/cerberus/mcp.stdout
grep -q '"blocking":false' target/cerberus/mcp.stdout
test ! -s target/cerberus/mcp.stderr

if cargo run --locked -- request git-range \
  --repo-path "$tmp_repo" \
  --base "$base_sha" \
  --head "$head_sha" \
  --local-runtime-command env \
  --out target/cerberus/context-tiers/forbidden-runtime-request.json \
  > target/cerberus/context-tiers/forbidden-runtime-request.stdout \
  2> target/cerberus/context-tiers/forbidden-runtime-request.stderr; then
  echo "expected local runtime request without policy to fail" >&2
  exit 1
fi
grep -q 'local runtime targets require policy.allow_local_runtime' \
  target/cerberus/context-tiers/forbidden-runtime-request.stderr

CERBERUS_ALLOWED_RUNTIME=visible cargo run --locked -- request git-range \
  --repo-path "$tmp_repo" \
  --base "$base_sha" \
  --head "$head_sha" \
  --local-runtime-command env \
  --allow-local-runtime \
  --allow-env CERBERUS_ALLOWED_RUNTIME \
  --out target/cerberus/context-tiers/local-runtime-request.json

GH_TOKEN=should-not-leak CERBERUS_ALLOWED_RUNTIME=visible cargo run --locked -- review \
  --request target/cerberus/context-tiers/local-runtime-request.json \
  --harness opencode \
  --opencode-binary "$PWD/fixtures/bin/fake-opencode" \
  --out target/cerberus/context-tiers/local-runtime-opencode-artifact.json \
  --execution-plan target/cerberus/context-tiers/local-runtime-opencode-execution_plan.json \
  --transcript target/cerberus/context-tiers/local-runtime-opencode-transcript.txt \
  --receipt-bundle target/cerberus/receipts/local-runtime-opencode.json

grep -q '"repo_base": true' target/cerberus/context-tiers/local-runtime-opencode-artifact.json
grep -q '"local_runtime": true' target/cerberus/context-tiers/local-runtime-opencode-artifact.json
grep -q '"workspace_mode": "repo_base_head_worktrees"' \
  target/cerberus/context-tiers/local-runtime-opencode-execution_plan.json
grep -q '"runtime_transcripts": \[' \
  target/cerberus/context-tiers/local-runtime-opencode-execution_plan.json
grep -q '\[local_runtime\]' target/cerberus/context-tiers/local-runtime-opencode-transcript.txt
grep -q 'CERBERUS_ALLOWED_RUNTIME=visible' \
  target/cerberus/context-tiers/local-runtime-opencode-transcript.txt
if grep -q 'GH_TOKEN=should-not-leak' \
  target/cerberus/context-tiers/local-runtime-opencode-transcript.txt; then
  echo "runtime probe leaked GH_TOKEN into transcript" >&2
  exit 1
fi

cargo run --locked -- review \
  --request fixtures/requests/diff-only.json \
  --harness fixture \
  --fixture-output fixtures/harness/valid-review.txt \
  --out target/cerberus/artifact.json \
  --markdown target/cerberus/review.md \
  --execution-plan target/cerberus/execution_plan.json \
  --transcript target/cerberus/transcript.txt \
  --receipt-bundle target/cerberus/receipts/fixture.json

cargo run --locked -- render \
  --artifact target/cerberus/artifact.json \
  --markdown target/cerberus/review-rendered.md

cargo run --locked -- review \
  --request fixtures/requests/diff-only.json \
  --harness fixture \
  --fixture-output fixtures/harness/valid-review.txt \
  --out target/cerberus/default-transcript/artifact.json \
  --receipt-bundle target/cerberus/default-transcript/receipt-bundle.json

test -s target/cerberus/default-transcript/transcript.txt
grep -q '"transcript_uri": "target/cerberus/default-transcript/transcript.txt"' \
  target/cerberus/default-transcript/receipt-bundle.json

GH_TOKEN=should-not-leak cargo run --locked -- review \
  --request fixtures/requests/diff-only.json \
  --harness opencode \
  --opencode-binary "$PWD/fixtures/bin/fake-opencode" \
  --out target/cerberus/opencode-artifact.json \
  --markdown target/cerberus/opencode-review.md \
  --execution-plan target/cerberus/opencode-execution_plan.json \
  --transcript target/cerberus/opencode-transcript.txt \
  --receipt-bundle target/cerberus/receipts/opencode.json

GH_TOKEN=should-not-leak cargo run --locked -- review \
  --request fixtures/requests/diff-only.json \
  --harness omp \
  --omp-binary "$PWD/fixtures/bin/fake-omp" \
  --out target/cerberus/omp-artifact.json \
  --markdown target/cerberus/omp-review.md \
  --execution-plan target/cerberus/omp-execution_plan.json \
  --transcript target/cerberus/omp-transcript.txt \
  --receipt-bundle target/cerberus/receipts/omp.json

fake_gh="$PWD/fixtures/bin/fake-gh"
fake_gh_state="target/cerberus/fake-gh-state"
fake_gh_token="target/cerberus/fake-gh-token.txt"
printf 'cerberus-fixture-token\n' > "$fake_gh_token"
rm -rf "$fake_gh_state"
CERBERUS_FAKE_GH_STATE_DIR="$fake_gh_state" \
CERBERUS_FAKE_GH_REQUIRE_TOKEN=1 \
CERBERUS_FAKE_GH_LOG=target/cerberus/review-pr-dry-run-gh.log \
cargo run --locked -- review-pr \
  --number 7 \
  --repo example/fixture \
  --gh-binary "$fake_gh" \
  --harness fixture \
  --fixture-output fixtures/harness/valid-review.txt \
  --out-dir target/cerberus/review-pr-dry-run \
  --receipt-bundle target/cerberus/receipts/review-pr-dry-run.json \
  --gh-token-file "$fake_gh_token" \
  --dry-run \
  > target/cerberus/review-pr-dry-run.stdout

grep -q '"schema_version": "cerberus.post_plan.v1"' target/cerberus/review-pr-dry-run/post-plan.json
grep -q '"id": "create-check-run"' target/cerberus/review-pr-dry-run/post-plan.json
grep -q '"path": "/repos/example/fixture/pulls/7/reviews"' target/cerberus/review-pr-dry-run/post-plan.json
grep -q '"line": 3' target/cerberus/review-pr-dry-run/post-plan.json
grep -q '"commit_id": "0123456789abcdef"' target/cerberus/review-pr-dry-run/post-plan.json
grep -q 'comment-001' target/cerberus/review-pr-dry-run/review.md
grep -q 'AUTH gh_token=present github_token=absent' target/cerberus/review-pr-dry-run-gh.log

remote_event=target/cerberus/weave-remote-event.json
cat > "$remote_event" <<'JSON'
{
  "schema_version": "weave.remote_event.v1",
  "id": "evt_github_fixture_review_pr",
  "producer": {"name": "github-adapter", "version": "0.1.0"},
  "produced_at": "2026-07-04T20:00:00Z",
  "occurred_at": "2026-07-04T19:59:58Z",
  "correlation_id": "github:example/fixture:pull_request:7:opened",
  "source": {
    "kind": "github",
    "host": "github.com",
    "external_id": "delivery-review-pr-7"
  },
  "repository": {
    "id": "repo-fixture",
    "full_name": "example/fixture",
    "default_branch": "main"
  },
  "subject": {
    "kind": "pull_request",
    "id": "7",
    "number": 7,
    "url": "https://github.com/example/fixture/pull/7"
  },
  "actor": {
    "id": "user-fixture",
    "login": "codex-worker",
    "kind": "bot"
  },
  "action": "opened",
  "idempotency_key": "github:delivery-review-pr-7:pull_request:7:opened:0123456789abcdef",
  "host_payload": {
    "event_name": "pull_request",
    "delivery_id": "delivery-review-pr-7",
    "api_version": "2022-11-28",
    "links": [
      {"rel": "html", "href": "https://github.com/example/fixture/pull/7"}
    ]
  },
  "policy": {
    "merge_policy": "human-review",
    "source": "repo-rule",
    "reason": "remote-event consumer smoke treats merge policy as input metadata only"
  },
  "payload": {
    "base_ref": "main",
    "head_ref": "fix/ratio-zero",
    "head_sha": "0123456789abcdef",
    "draft": false,
    "state": "open"
  }
}
JSON
rm -rf "$fake_gh_state"
CERBERUS_FAKE_GH_STATE_DIR="$fake_gh_state" \
CERBERUS_FAKE_GH_REQUIRE_TOKEN=1 \
CERBERUS_FAKE_GH_LOG=target/cerberus/review-pr-remote-event-gh.log \
cargo run --locked -- review-pr \
  --remote-event "$remote_event" \
  --gh-binary "$fake_gh" \
  --harness fixture \
  --fixture-output fixtures/harness/valid-review.txt \
  --out-dir target/cerberus/review-pr-remote-event \
  --receipt-bundle target/cerberus/receipts/review-pr-remote-event.json \
  --gh-token-file "$fake_gh_token" \
  --dry-run \
  > target/cerberus/review-pr-remote-event.stdout
grep -Eq 'PR_VIEW 7 .* -R example/fixture' target/cerberus/review-pr-remote-event-gh.log
grep -Eq 'PR_DIFF 7 .* -R example/fixture' target/cerberus/review-pr-remote-event-gh.log
python3 - <<'PY'
import json
request = json.load(open("target/cerberus/review-pr-remote-event/request.json", encoding="utf-8"))
event = request["source"]["metadata"]["remote_event"]
assert event["schema_version"] == "weave.remote_event.v1"
assert event["repository"]["full_name"] == "example/fixture"
assert event["subject"]["number"] == 7
assert event["actor"]["login"] == "codex-worker"
assert event["action"] == "opened"
assert event["payload"]["head_sha"] == "0123456789abcdef"
assert event["policy"]["merge_policy"] == "human-review"
assert "normalized remote-event envelope" in "\n".join(request["context"]["instructions"])
PY

unknown_remote_event=target/cerberus/weave-remote-event-unknown-major.json
python3 - <<'PY'
import json
event = json.load(open("target/cerberus/weave-remote-event.json", encoding="utf-8"))
event["schema_version"] = "weave.remote_event.v2"
with open("target/cerberus/weave-remote-event-unknown-major.json", "w", encoding="utf-8") as fh:
    json.dump(event, fh)
    fh.write("\n")
PY
rm -rf "$fake_gh_state"
rm -f target/cerberus/review-pr-remote-event-unknown-gh.log
if CERBERUS_FAKE_GH_STATE_DIR="$fake_gh_state" \
  CERBERUS_FAKE_GH_LOG=target/cerberus/review-pr-remote-event-unknown-gh.log \
  cargo run --locked -- review-pr \
    --remote-event "$unknown_remote_event" \
    --gh-binary "$fake_gh" \
    --harness fixture \
    --fixture-output fixtures/harness/valid-review.txt \
    --out-dir target/cerberus/review-pr-remote-event-unknown \
    --gh-token-file "$fake_gh_token" \
    --dry-run \
    > target/cerberus/review-pr-remote-event-unknown.stdout \
    2> target/cerberus/review-pr-remote-event-unknown.stderr; then
  echo "expected review-pr remote-event to reject unknown major schema_version" >&2
  exit 1
fi
grep -q 'unsupported remote event schema_version weave.remote_event.v2' \
  target/cerberus/review-pr-remote-event-unknown.stderr
if [[ -s target/cerberus/review-pr-remote-event-unknown-gh.log ]]; then
  echo "review-pr remote-event read GitHub before rejecting unknown major schema_version" >&2
  exit 1
fi

rm -rf "$fake_gh_state"
mkdir -p target/cerberus/review-pr-dry-run-no-token
printf 'stale post result\n' > target/cerberus/review-pr-dry-run-no-token/post-result.json
printf 'stale post plan\n' > target/cerberus/review-pr-dry-run-no-token/post-plan.json
if GH_TOKEN=ambient-should-not-count \
  CERBERUS_FAKE_GH_STATE_DIR="$fake_gh_state" \
  CERBERUS_FAKE_GH_LOG=target/cerberus/review-pr-dry-run-no-token-gh.log \
  cargo run --locked -- review-pr \
    --number 7 \
    --repo example/fixture \
    --gh-binary "$fake_gh" \
    --harness fixture \
    --fixture-output fixtures/harness/valid-review.txt \
    --out-dir target/cerberus/review-pr-dry-run-no-token \
    --summary-target check-run \
    --dry-run \
    > target/cerberus/review-pr-dry-run-no-token.stdout \
    2> target/cerberus/review-pr-dry-run-no-token.stderr; then
  echo "expected review-pr dry-run to refuse ambient auth without explicit token" >&2
  exit 1
fi
grep -q 'requires an explicit GitHub token' target/cerberus/review-pr-dry-run-no-token.stderr
test ! -e target/cerberus/review-pr-dry-run-no-token/post-result.json
test ! -e target/cerberus/review-pr-dry-run-no-token/post-plan.json
if [[ -s target/cerberus/review-pr-dry-run-no-token-gh.log ]]; then
  echo "review-pr dry-run read GitHub without explicit token" >&2
  exit 1
fi

rm -rf "$fake_gh_state"
mkdir -p target/cerberus/review-pr-post-no-token
printf 'stale post result\n' > target/cerberus/review-pr-post-no-token/post-result.json
printf 'stale post plan\n' > target/cerberus/review-pr-post-no-token/post-plan.json
if CERBERUS_FAKE_GH_STATE_DIR="$fake_gh_state" \
  CERBERUS_FAKE_GH_LOG=target/cerberus/review-pr-post-no-token-gh.log \
  cargo run --locked -- review-pr \
    --number 7 \
    --repo example/fixture \
    --gh-binary "$fake_gh" \
    --harness fixture \
    --fixture-output fixtures/harness/valid-review.txt \
    --out-dir target/cerberus/review-pr-post-no-token \
    --summary-target check-run \
    --post \
    > target/cerberus/review-pr-post-no-token.stdout \
    2> target/cerberus/review-pr-post-no-token.stderr; then
  echo "expected review-pr post to refuse ambient auth without explicit token" >&2
  exit 1
fi
grep -q 'requires an explicit GitHub token' target/cerberus/review-pr-post-no-token.stderr
test ! -e target/cerberus/review-pr-post-no-token/post-result.json
test ! -e target/cerberus/review-pr-post-no-token/post-plan.json
if [[ -e target/cerberus/review-pr-post-no-token-gh.log ]] && \
  grep -q '^POST ' target/cerberus/review-pr-post-no-token-gh.log; then
  echo "review-pr posted without explicit token" >&2
  exit 1
fi

rm -rf "$fake_gh_state"
if CERBERUS_FAKE_GH_STATE_DIR="$fake_gh_state" \
  CERBERUS_FAKE_GH_LOG=target/cerberus/review-pr-post-both-token-sources-gh.log \
  CERBERUS_REVIEW_POST_TOKEN=cerberus-fixture-token \
  cargo run --locked -- review-pr \
    --number 7 \
    --repo example/fixture \
    --gh-binary "$fake_gh" \
    --harness fixture \
    --fixture-output fixtures/harness/valid-review.txt \
    --out-dir target/cerberus/review-pr-post-both-token-sources \
    --summary-target check-run \
    --gh-token-file "$fake_gh_token" \
    --gh-token-env CERBERUS_REVIEW_POST_TOKEN \
    --post \
    > target/cerberus/review-pr-post-both-token-sources.stdout \
    2> target/cerberus/review-pr-post-both-token-sources.stderr; then
  echo "expected review-pr post to reject multiple explicit token sources" >&2
  exit 1
fi
grep -q 'exactly one explicit GitHub token source' \
  target/cerberus/review-pr-post-both-token-sources.stderr

rm -rf "$fake_gh_state"
if CERBERUS_FAKE_GH_STATE_DIR="$fake_gh_state" \
  CERBERUS_FAKE_GH_REQUIRE_TOKEN=1 \
  CERBERUS_FAKE_GH_FAIL_PR_VIEW=1 \
  CERBERUS_REVIEW_POST_TOKEN=cerberus-fixture-token \
  cargo run --locked -- review-pr \
    --number 7 \
    --repo example/fixture \
    --gh-binary "$fake_gh" \
    --harness fixture \
    --fixture-output fixtures/harness/valid-review.txt \
    --out-dir target/cerberus/review-pr-post-pr-view-token-leak \
    --summary-target check-run \
    --gh-token-env CERBERUS_REVIEW_POST_TOKEN \
    --post \
    > target/cerberus/review-pr-post-pr-view-token-leak.stdout \
    2> target/cerberus/review-pr-post-pr-view-token-leak.stderr; then
  echo "expected injected-token pr view failure" >&2
  exit 1
fi
grep -q 'GH_TOKEN=<redacted>' target/cerberus/review-pr-post-pr-view-token-leak.stderr
if grep -q 'cerberus-fixture-token' target/cerberus/review-pr-post-pr-view-token-leak.stderr; then
  echo "pr view failure leaked injected token" >&2
  exit 1
fi

rm -rf "$fake_gh_state"
if CERBERUS_FAKE_GH_STATE_DIR="$fake_gh_state" \
  CERBERUS_FAKE_GH_REQUIRE_TOKEN=1 \
  CERBERUS_FAKE_GH_FAIL_PR_DIFF=1 \
  cargo run --locked -- review-pr \
    --number 7 \
    --repo example/fixture \
    --gh-binary "$fake_gh" \
    --harness fixture \
    --fixture-output fixtures/harness/valid-review.txt \
    --out-dir target/cerberus/review-pr-post-pr-diff-token-leak \
    --summary-target check-run \
    --gh-token-file "$fake_gh_token" \
    --post \
    > target/cerberus/review-pr-post-pr-diff-token-leak.stdout \
    2> target/cerberus/review-pr-post-pr-diff-token-leak.stderr; then
  echo "expected injected-token pr diff failure" >&2
  exit 1
fi
grep -q 'GH_TOKEN=<redacted>' target/cerberus/review-pr-post-pr-diff-token-leak.stderr
if grep -q 'cerberus-fixture-token' target/cerberus/review-pr-post-pr-diff-token-leak.stderr; then
  echo "pr diff failure leaked injected token" >&2
  exit 1
fi

rm -rf "$fake_gh_state"
if CERBERUS_FAKE_GH_STATE_DIR="$fake_gh_state" \
  CERBERUS_FAKE_GH_REQUIRE_TOKEN=1 \
  CERBERUS_FAKE_GH_FAIL_API=1 \
  cargo run --locked -- review-pr \
    --number 7 \
    --repo example/fixture \
    --gh-binary "$fake_gh" \
    --harness fixture \
    --fixture-output fixtures/harness/valid-review.txt \
    --out-dir target/cerberus/review-pr-post-api-token-leak \
    --summary-target check-run \
    --gh-token-file "$fake_gh_token" \
    --post \
    > target/cerberus/review-pr-post-api-token-leak.stdout \
    2> target/cerberus/review-pr-post-api-token-leak.stderr; then
  echo "expected injected-token api failure" >&2
  exit 1
fi
grep -q 'GH_TOKEN=<redacted>' target/cerberus/review-pr-post-api-token-leak.stderr
if grep -q 'cerberus-fixture-token' target/cerberus/review-pr-post-api-token-leak.stderr; then
  echo "api failure leaked injected token" >&2
  exit 1
fi

rm -rf "$fake_gh_state"
if CERBERUS_FAKE_GH_STATE_DIR="$fake_gh_state" \
  CERBERUS_FAKE_GH_MOVED_HEAD_SHA=feedfacefeedface \
  cargo run --locked -- review-pr \
    --number 7 \
    --repo example/fixture \
    --gh-binary "$fake_gh" \
    --harness fixture \
    --fixture-output fixtures/harness/valid-review.txt \
    --out-dir target/cerberus/review-pr-stale-head \
    --gh-token-file "$fake_gh_token" \
    --dry-run \
    > target/cerberus/review-pr-stale-head.stdout \
    2> target/cerberus/review-pr-stale-head.stderr; then
  echo "expected review-pr to reject a moved PR head" >&2
  exit 1
fi
grep -q 'head moved from 0123456789abcdef to feedfacefeedface' target/cerberus/review-pr-stale-head.stderr
test ! -e target/cerberus/review-pr-stale-head/receipt-bundle.json

rm -rf "$fake_gh_state"
if CERBERUS_FAKE_GH_STATE_DIR="$fake_gh_state" \
  CERBERUS_FAKE_GH_REQUIRE_TOKEN=1 \
  CERBERUS_FAKE_GH_MOVED_HEAD_SHA=feedfacefeedface \
  CERBERUS_FAKE_GH_MOVE_HEAD_AFTER_VIEW_COUNT=3 \
  CERBERUS_FAKE_GH_LOG=target/cerberus/review-pr-post-final-stale-gh.log \
  cargo run --locked -- review-pr \
    --number 7 \
    --repo example/fixture \
    --gh-binary "$fake_gh" \
    --harness fixture \
    --fixture-output fixtures/harness/valid-review.txt \
    --out-dir target/cerberus/review-pr-post-final-stale \
    --summary-target check-run \
    --gh-token-file "$fake_gh_token" \
    --post \
    > target/cerberus/review-pr-post-final-stale.stdout \
    2> target/cerberus/review-pr-post-final-stale.stderr; then
  echo "expected review-pr post to reject a PR head moved after post-plan creation" >&2
  exit 1
fi
grep -q 'head moved from 0123456789abcdef to feedfacefeedface' \
  target/cerberus/review-pr-post-final-stale.stderr
test ! -e target/cerberus/review-pr-post-final-stale/receipt-bundle.json
test ! -e target/cerberus/review-pr-post-final-stale/post-result.json
if grep -q '^POST ' target/cerberus/review-pr-post-final-stale-gh.log; then
  echo "review-pr posted after final stale-head guard failed" >&2
  exit 1
fi

rm -rf "$fake_gh_state"
CERBERUS_FAKE_GH_STATE_DIR="$fake_gh_state" \
CERBERUS_FAKE_GH_REQUIRE_TOKEN=1 \
CERBERUS_FAKE_GH_LOG=target/cerberus/review-pr-post-first-gh.log \
cargo run --locked -- review-pr \
  --number 7 \
  --repo example/fixture \
  --gh-binary "$fake_gh" \
  --harness fixture \
  --fixture-output fixtures/harness/valid-review.txt \
  --out-dir target/cerberus/review-pr-post-first \
  --summary-target check-run \
  --gh-token-file "$fake_gh_token" \
  --post

CERBERUS_FAKE_GH_STATE_DIR="$fake_gh_state" \
CERBERUS_FAKE_GH_REQUIRE_TOKEN=1 \
CERBERUS_FAKE_GH_LOG=target/cerberus/review-pr-post-second-gh.log \
cargo run --locked -- review-pr \
  --number 7 \
  --repo example/fixture \
  --gh-binary "$fake_gh" \
  --harness fixture \
  --fixture-output fixtures/harness/valid-review.txt \
  --out-dir target/cerberus/review-pr-post-second \
  --summary-target check-run \
  --gh-token-file "$fake_gh_token" \
  --post

CERBERUS_FAKE_GH_STATE_DIR="$fake_gh_state" \
CERBERUS_FAKE_GH_REQUIRE_TOKEN=1 \
CERBERUS_FAKE_GH_MARKERS_ON_PAGE_2=1 \
CERBERUS_FAKE_GH_LOG=target/cerberus/review-pr-post-page-two-gh.log \
cargo run --locked -- review-pr \
  --number 7 \
  --repo example/fixture \
  --gh-binary "$fake_gh" \
  --harness fixture \
  --fixture-output fixtures/harness/valid-review.txt \
  --out-dir target/cerberus/review-pr-post-page-two \
  --summary-target check-run \
  --gh-token-file "$fake_gh_token" \
  --post

test -s target/cerberus/artifact.json
test -s target/cerberus/review.md
test -s target/cerberus/review-rendered.md
test -s target/cerberus/execution_plan.json
test -s target/cerberus/transcript.txt
test -s target/cerberus/reviewer_plan.json
test -s target/cerberus/git-range-request.json
test -s target/cerberus/git-range-artifact.json
test -s target/cerberus/git-range-review.md
test -s target/cerberus/git-range-execution_plan.json
test -s target/cerberus/git-range-reviewer_plan.json
test -s target/cerberus/mcp.stdout
test -s target/cerberus/git-range-opencode-artifact.json
test -s target/cerberus/git-range-opencode-review.md
test -s target/cerberus/git-range-opencode-execution_plan.json
test -s target/cerberus/git-range-opencode-transcript.txt
test -s target/cerberus/git-range-opencode-reviewer_plan.json
test -s target/cerberus/context-tiers/local-runtime-request.json
test -s target/cerberus/context-tiers/local-runtime-opencode-artifact.json
test -s target/cerberus/context-tiers/local-runtime-opencode-execution_plan.json
test -s target/cerberus/context-tiers/local-runtime-opencode-transcript.txt
test -s target/cerberus/context-tiers/local-runtime-opencode-reviewer_plan.json
test -s target/cerberus/opencode-artifact.json
test -s target/cerberus/opencode-execution_plan.json
test -s target/cerberus/opencode-transcript.txt
test -s target/cerberus/opencode-reviewer_plan.json
test -s target/cerberus/omp-artifact.json
test -s target/cerberus/omp-execution_plan.json
test -s target/cerberus/omp-transcript.txt
test -s target/cerberus/omp-reviewer_plan.json
test -s target/cerberus/review-pr-dry-run/request.json
test -s target/cerberus/review-pr-dry-run/artifact.json
test -s target/cerberus/review-pr-dry-run/review.md
test -s target/cerberus/review-pr-dry-run/execution_plan.json
test -s target/cerberus/review-pr-dry-run/reviewer_plan.json
test -s target/cerberus/review-pr-dry-run/transcript.txt
test -s target/cerberus/review-pr-dry-run/post-plan.json
test -s target/cerberus/review-pr-post-first/post-result.json
test -s target/cerberus/review-pr-post-first/receipt-bundle.json
test -s target/cerberus/review-pr-post-second/post-result.json
test -s target/cerberus/review-pr-post-second/receipt-bundle.json
test -s target/cerberus/review-pr-post-page-two/post-result.json
test -s target/cerberus/review-pr-post-page-two/receipt-bundle.json
test -s target/cerberus/receipts/fixture.json
test -s target/cerberus/receipts/opencode.json
test -s target/cerberus/receipts/omp.json
test -s target/cerberus/receipts/git-range-fixture.json
test -s target/cerberus/receipts/git-range-opencode.json
test -s target/cerberus/receipts/invalid-secret-schema.json
test -s target/cerberus/receipts/local-runtime-opencode.json
test -s target/cerberus/receipts/review-pr-dry-run.json

grep -q '"private_material_in_argv": false' target/cerberus/execution_plan.json
grep -q '"diff": true' target/cerberus/artifact.json
grep -q '"repo_head": false' target/cerberus/artifact.json
grep -q '"repo_head": true' target/cerberus/git-range-artifact.json
grep -q '"repo_base": true' target/cerberus/git-range-artifact.json
grep -q '"repo_head": true' target/cerberus/git-range-opencode-artifact.json
grep -q '"repo_base": true' target/cerberus/git-range-opencode-artifact.json
grep -q '"workspace_mode": "repo_base_head_worktrees"' target/cerberus/git-range-opencode-execution_plan.json
grep -q 'Cerberus Review: WARN' target/cerberus/review.md
grep -q '"harness": "opencode"' target/cerberus/opencode-execution_plan.json
grep -q '"harness": "omp"' target/cerberus/omp-execution_plan.json
grep -q '"workspace_mode": "diff_packet"' target/cerberus/opencode-execution_plan.json
grep -q '"workspace_mode": "diff_packet"' target/cerberus/omp-execution_plan.json
grep -q '<request-file>' target/cerberus/opencode-execution_plan.json
grep -q '<request-file>' target/cerberus/git-range-opencode-execution_plan.json
grep -q '<prompt-file>' target/cerberus/omp-execution_plan.json
python3 - <<'PY'
import json

with open("target/cerberus/reviewer_plan.json", encoding="utf-8") as fh:
    plan = json.load(fh)
assert plan["schema_version"] == "cerberus.reviewer_plan.v1"
assert plan["lane_decision"]["mode"] == "single_master"
assert len(plan["child_lanes"]) == 0
assert plan["master_lane"]["expected_output"] == "ReviewArtifact.v1"
assert plan["diff_understanding"]["changed_surfaces"][0]["path"] == "src/ratio.rs"

with open(
    "target/cerberus/context-tiers/local-runtime-opencode-reviewer_plan.json",
    encoding="utf-8",
) as fh:
    local_plan = json.load(fh)
assert local_plan["diff_understanding"]["available_context"]["local_runtime"] is True
assert local_plan["master_lane"]["allowed_context_tier"] == "local_runtime"
assert "local_runtime" not in local_plan["diff_understanding"]["skipped_context"]
PY
grep -q '"schema_version": "cerberus.review_receipt_bundle.v1"' target/cerberus/receipts/opencode.json
grep -q '"harness": "opencode"' target/cerberus/receipts/opencode.json
grep -q '"model": "fake/opencode-reviewer"' target/cerberus/receipts/opencode.json
grep -q '"prompt_tokens": 123' target/cerberus/receipts/opencode.json
grep -q '"completion_tokens": 45' target/cerberus/receipts/opencode.json
grep -q '"cost_usd": 0.0042' target/cerberus/receipts/opencode.json
grep -q '"validation": {' target/cerberus/receipts/opencode.json
grep -q '"trusted_for_posting": true' target/cerberus/receipts/opencode.json
grep -q '"reviewer_plan_uri": "target/cerberus/reviewer_plan.json"' target/cerberus/receipts/fixture.json
grep -q '"capability_tier": "diff_only"' target/cerberus/receipts/fixture.json
grep -q '"capability_tier": "repo_base_and_head"' target/cerberus/receipts/git-range-opencode.json
grep -q '"capability_tier": "local_runtime"' target/cerberus/receipts/local-runtime-opencode.json
grep -q '"transcript_uri": "target/cerberus/opencode-transcript.txt"' target/cerberus/receipts/opencode.json
if grep -R 'GH_TOKEN\|should-not-leak\|master-prompt.md\|review-request.json' target/cerberus/receipts; then
  echo "receipt bundle leaked private prompt/request material or secret names" >&2
  exit 1
fi
grep -q 'POST /repos/example/fixture/check-runs' target/cerberus/review-pr-post-first-gh.log
grep -q 'POST /repos/example/fixture/pulls/7/reviews' target/cerberus/review-pr-post-first-gh.log
grep -q 'AUTH gh_token=present github_token=absent' target/cerberus/review-pr-post-first-gh.log
grep -q 'GET /repos/example/fixture/issues/7/comments?per_page=100&page=1' target/cerberus/review-pr-post-first-gh.log
grep -q 'GET /repos/example/fixture/pulls/7/comments?per_page=100&page=1' target/cerberus/review-pr-post-first-gh.log
grep -q 'GET /repos/example/fixture/commits/0123456789abcdef/check-runs?check_name=Cerberus%20Review&per_page=100&page=1' target/cerberus/review-pr-post-first-gh.log
grep -q 'PATCH /repos/example/fixture/check-runs/501' target/cerberus/review-pr-post-second-gh.log
grep -q 'PATCH /repos/example/fixture/issues/comments/101' target/cerberus/review-pr-post-second-gh.log
grep -q 'PATCH /repos/example/fixture/pulls/comments/201' target/cerberus/review-pr-post-second-gh.log
grep -q 'GET /repos/example/fixture/issues/7/comments?per_page=100&page=2' target/cerberus/review-pr-post-page-two-gh.log
grep -q 'GET /repos/example/fixture/pulls/7/comments?per_page=100&page=2' target/cerberus/review-pr-post-page-two-gh.log
grep -q 'GET /repos/example/fixture/commits/0123456789abcdef/check-runs?check_name=Cerberus%20Review&per_page=100&page=2' target/cerberus/review-pr-post-page-two-gh.log
grep -q 'PATCH /repos/example/fixture/check-runs/501' target/cerberus/review-pr-post-page-two-gh.log
grep -q 'PATCH /repos/example/fixture/issues/comments/101' target/cerberus/review-pr-post-page-two-gh.log
grep -q 'PATCH /repos/example/fixture/pulls/comments/201' target/cerberus/review-pr-post-page-two-gh.log

# Backlog 013 M2 (slice 1): container-opencode red-team family. Proves the
# containment boundary the same way M1 proved the credential boundary — by
# actually trying the attack and showing it fails, not by inspecting code.
# Gated on Docker: skipped (not failed) when the daemon isn't reachable, per
# the ticket's own gate contract ("container path skipped when Docker
# absent"). --container-host-root must be under a path the Docker daemon can
# actually see: on native Docker (Linux, GH Actions runners) any path works,
# but a daemon running inside a VM with a narrow mount allowlist (colima's
# default: only $HOME) needs it pointed inside the checkout, not the OS temp
# dir -- otherwise -v mounts silently resolve empty instead of failing loudly.
if docker info > /dev/null 2>&1; then
  container_host_root="target/cerberus/container-hostroot"
  redteam_substrate="$PWD/fixtures/bin/redteam-container-substrate"
  rm_container_workdirs() {
    rm -rf "$container_host_root"
  }
  rm_container_workdirs
  mkdir -p "$container_host_root"

  run_redteam_container_review() {
    local name="$1"
    local request="$2"
    if ! cargo run --locked -- review \
      --request "$request" \
      --harness container-opencode \
      --container-binary "$redteam_substrate" \
      --container-host-root "$container_host_root" \
      --out "target/cerberus/${name}-artifact.json" \
      --transcript "target/cerberus/${name}-transcript.txt" \
      --timeout-seconds 60 \
      > "target/cerberus/${name}.stdout" \
      2> "target/cerberus/${name}.stderr"; then
      echo "container-opencode red-team review ${name} failed; stderr:" >&2
      cat "target/cerberus/${name}.stderr" >&2
      exit 1
    fi
  }

  assert_redteam_contained() {
    local name="$1"
    local transcript="target/cerberus/${name}-transcript.txt"
    test -s "target/cerberus/${name}-artifact.json"
    grep -q '"verdict"' "target/cerberus/${name}-artifact.json"
    if ! grep -q '\[redteam-results\]' "$transcript"; then
      echo "red-team substrate never reported results for ${name}" >&2
      exit 1
    fi
    if grep -q '"dns_lookup_exit_code": 0' "$transcript"; then
      echo "container-opencode did not block DNS egress in ${name}" >&2
      exit 1
    fi
    if grep -q '"egress_connect_exit_code": 0' "$transcript"; then
      echo "container-opencode did not block non-model network egress in ${name}" >&2
      exit 1
    fi
    if grep -q '"outside_mount_write_exit_code": 0' "$transcript"; then
      echo "container-opencode did not block a file-write escape outside the mount in ${name}" >&2
      exit 1
    fi
    if grep -q '"traversal_write_exit_code": 0' "$transcript"; then
      echo "container-opencode did not block a path-traversal file-write escape in ${name}" >&2
      exit 1
    fi
    if ! grep -q '"dot_git_present": false' "$transcript"; then
      echo "container-opencode mounted tree carries a .git handle in ${name} (worktree-escape risk)" >&2
      exit 1
    fi
    # Backlog 013 M2 slice 2: containment must carve exactly one working
    # exception (the model API through the egress proxy), not just deny
    # everything -- prove the CONNECT tunnel to the allowed host succeeds.
    if ! grep -q '"allowed_connect_status": "HTTP/1.1 200 Connection established"' "$transcript"; then
      echo "container-opencode did not allow the model-API CONNECT tunnel in ${name}" >&2
      exit 1
    fi
  }

  # Diff-only: no repo checkout, exercises the network/filesystem escape
  # vectors without needing a git-archive extraction.
  run_redteam_container_review "redteam-diff-only" fixtures/requests/redteam-diff-only.json
  assert_redteam_contained redteam-diff-only

  # repo_head: a real disposable source repo, archived via `git archive` (not
  # `git worktree add`) into the container mount. This is the case that
  # actually exercises the .git-less claim -- diff-only mode has no .git
  # either way, so it can't tell a git-archive extraction from a plain
  # directory. Digest the host repo before/after to prove the container
  # substrate never touched the real checkout (only the archived copy).
  redteam_source_repo="$PWD/target/cerberus/redteam-source-repo"
  rm -rf "$redteam_source_repo"
  mkdir -p "$redteam_source_repo"
  git -C "$redteam_source_repo" init -q
  git -C "$redteam_source_repo" config user.email redteam@example.com
  git -C "$redteam_source_repo" config user.name "Cerberus Redteam Fixture"
  echo 'fn main() {}' > "$redteam_source_repo/main.rs"
  git -C "$redteam_source_repo" add .
  git -C "$redteam_source_repo" commit -q -m init
  redteam_source_sha="$(git -C "$redteam_source_repo" rev-parse HEAD)"

  python3 - "$redteam_source_repo" "$redteam_source_sha" <<'PY'
import json
import sys

repo_path, sha = sys.argv[1], sys.argv[2]
with open("fixtures/requests/redteam-diff-only.json", encoding="utf-8") as fh:
    request = json.load(fh)
request["request_id"] = "fixture-redteam-repo-head-001"
request["context"]["workspaces"] = {
    "head": {"kind": "checkout", "path": repo_path, "sha": sha}
}
with open("target/cerberus/redteam-repo-head-request.json", "w", encoding="utf-8") as fh:
    json.dump(request, fh, indent=2)
PY

  host_head_before="$(git -C "$redteam_source_repo" rev-parse HEAD)"
  host_status_before="$(git -C "$redteam_source_repo" status --porcelain)"

  run_redteam_container_review "redteam-repo-head" target/cerberus/redteam-repo-head-request.json
  assert_redteam_contained redteam-repo-head

  host_head_after="$(git -C "$redteam_source_repo" rev-parse HEAD)"
  host_status_after="$(git -C "$redteam_source_repo" status --porcelain)"
  if [[ "$host_head_before" != "$host_head_after" ]]; then
    echo "container-opencode review mutated the host checkout's HEAD ($host_head_before -> $host_head_after)" >&2
    exit 1
  fi
  if [[ -n "$host_status_after" ]]; then
    echo "container-opencode review left the host checkout dirty: $host_status_after" >&2
    exit 1
  fi
  if [[ -n "$host_status_before" ]]; then
    echo "host checkout was unexpectedly dirty before the container review even ran" >&2
    exit 1
  fi

  # Backlog 013 M2: orphaned-container sweeper, parallel to M1's orphan-key
  # sweeper. Fabricate a container and a network carrying an old timestamp
  # in their names (as if a prior run had been SIGKILLed after creating
  # them) and confirm the very next container-opencode run's sweep step
  # removes them, logging that it did.
  orphan_ts=$(($(date +%s) - 7200))
  orphan_container="cerberus-review-${orphan_ts}-verifysweep"
  orphan_network="cerberus-review-net-${orphan_ts}-verifysweep"
  docker run -d --name "$orphan_container" alpine:3.20 sleep 300 > /dev/null
  docker network create "$orphan_network" > /dev/null

  if ! cargo run --locked -- review \
    --request fixtures/requests/redteam-diff-only.json \
    --harness container-opencode \
    --container-binary "$redteam_substrate" \
    --container-host-root "$container_host_root" \
    --container-orphan-sweep-seconds 60 \
    --out target/cerberus/orphan-sweep-artifact.json \
    --transcript target/cerberus/orphan-sweep-transcript.txt \
    --timeout-seconds 60 \
    > target/cerberus/orphan-sweep.stdout \
    2> target/cerberus/orphan-sweep.stderr; then
    echo "orphan-sweep verification review itself failed; stderr:" >&2
    cat target/cerberus/orphan-sweep.stderr >&2
    exit 1
  fi
  if ! grep -q 'orphan sweep removed' target/cerberus/orphan-sweep.stderr; then
    echo "container-opencode did not log an orphan sweep on a run that should have found stale resources" >&2
    cat target/cerberus/orphan-sweep.stderr >&2
    exit 1
  fi
  if docker ps -a --filter "name=${orphan_container}" --format '{{.Names}}' | grep -q .; then
    echo "orphan sweeper left the stale container ${orphan_container} running" >&2
    exit 1
  fi
  if docker network ls --filter "name=${orphan_network}" --format '{{.Name}}' | grep -q .; then
    echo "orphan sweeper left the stale network ${orphan_network} in place" >&2
    exit 1
  fi

  rm_container_workdirs
else
  echo "docker not reachable; skipping backlog 013 M2 container-opencode red-team family" >&2
fi

if [[ "${CERBERUS_LIVE_REVIEW_PR:-}" == "1" ]]; then
  : "${CERBERUS_LIVE_REVIEW_REPO:?set CERBERUS_LIVE_REVIEW_REPO=owner/name}"
  : "${CERBERUS_LIVE_REVIEW_NUMBER:?set CERBERUS_LIVE_REVIEW_NUMBER=<pull request number>}"
  live_out="target/cerberus/live-review-pr"
  live_mode=(--dry-run)
  live_token_args=()
  if [[ -n "${CERBERUS_LIVE_REVIEW_GH_TOKEN_FILE:-}" && -n "${CERBERUS_LIVE_REVIEW_GH_TOKEN_ENV:-}" ]]; then
    echo "set only one of CERBERUS_LIVE_REVIEW_GH_TOKEN_FILE or CERBERUS_LIVE_REVIEW_GH_TOKEN_ENV" >&2
    exit 1
  elif [[ -n "${CERBERUS_LIVE_REVIEW_GH_TOKEN_FILE:-}" ]]; then
    live_token_args+=(--gh-token-file "$CERBERUS_LIVE_REVIEW_GH_TOKEN_FILE")
  elif [[ -n "${CERBERUS_LIVE_REVIEW_GH_TOKEN_ENV:-}" ]]; then
    live_token_args+=(--gh-token-env "$CERBERUS_LIVE_REVIEW_GH_TOKEN_ENV")
  else
    echo "live review requires CERBERUS_LIVE_REVIEW_GH_TOKEN_FILE or CERBERUS_LIVE_REVIEW_GH_TOKEN_ENV" >&2
    exit 1
  fi
  if [[ "${CERBERUS_LIVE_REVIEW_POST:-}" == "1" ]]; then
    live_mode=(--post)
  fi
  cargo run --locked -- review-pr \
    --number "$CERBERUS_LIVE_REVIEW_NUMBER" \
    --repo "$CERBERUS_LIVE_REVIEW_REPO" \
    --out-dir "$live_out" \
    --summary-target "${CERBERUS_LIVE_REVIEW_SUMMARY_TARGET:-status}" \
    --harness "${CERBERUS_LIVE_REVIEW_HARNESS:-opencode}" \
    "${live_token_args[@]}" \
    "${live_mode[@]}"
fi
