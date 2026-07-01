#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --locked

cargo run --locked -- review --help > target/cerberus-review-help.txt
grep -q '\[default: opencode\]' target/cerberus-review-help.txt
grep -q 'possible values: opencode, omp, fixture' target/cerberus-review-help.txt
grep -q -- '--receipt-bundle' target/cerberus-review-help.txt
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
CERBERUS_FAKE_GH_STATE_DIR="$fake_gh_state" cargo run --locked -- review-pr \
  --number 7 \
  --repo example/fixture \
  --gh-binary "$fake_gh" \
  --harness fixture \
  --fixture-output fixtures/harness/valid-review.txt \
  --out-dir target/cerberus/review-pr-dry-run \
  --receipt-bundle target/cerberus/receipts/review-pr-dry-run.json \
  --dry-run \
  > target/cerberus/review-pr-dry-run.stdout

grep -q '"schema_version": "cerberus.post_plan.v1"' target/cerberus/review-pr-dry-run/post-plan.json
grep -q '"id": "create-check-run"' target/cerberus/review-pr-dry-run/post-plan.json
grep -q '"path": "/repos/example/fixture/pulls/7/reviews"' target/cerberus/review-pr-dry-run/post-plan.json
grep -q '"line": 3' target/cerberus/review-pr-dry-run/post-plan.json
grep -q '"commit_id": "0123456789abcdef"' target/cerberus/review-pr-dry-run/post-plan.json
grep -q 'comment-001' target/cerberus/review-pr-dry-run/review.md

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
test -s target/cerberus/git-range-request.json
test -s target/cerberus/git-range-artifact.json
test -s target/cerberus/git-range-review.md
test -s target/cerberus/git-range-execution_plan.json
test -s target/cerberus/mcp.stdout
test -s target/cerberus/git-range-opencode-artifact.json
test -s target/cerberus/git-range-opencode-review.md
test -s target/cerberus/git-range-opencode-execution_plan.json
test -s target/cerberus/git-range-opencode-transcript.txt
test -s target/cerberus/context-tiers/local-runtime-request.json
test -s target/cerberus/context-tiers/local-runtime-opencode-artifact.json
test -s target/cerberus/context-tiers/local-runtime-opencode-execution_plan.json
test -s target/cerberus/context-tiers/local-runtime-opencode-transcript.txt
test -s target/cerberus/opencode-artifact.json
test -s target/cerberus/opencode-execution_plan.json
test -s target/cerberus/opencode-transcript.txt
test -s target/cerberus/omp-artifact.json
test -s target/cerberus/omp-execution_plan.json
test -s target/cerberus/omp-transcript.txt
test -s target/cerberus/review-pr-dry-run/request.json
test -s target/cerberus/review-pr-dry-run/artifact.json
test -s target/cerberus/review-pr-dry-run/review.md
test -s target/cerberus/review-pr-dry-run/execution_plan.json
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
grep -q '"schema_version": "cerberus.review_receipt_bundle.v1"' target/cerberus/receipts/opencode.json
grep -q '"harness": "opencode"' target/cerberus/receipts/opencode.json
grep -q '"model": "fake/opencode-reviewer"' target/cerberus/receipts/opencode.json
grep -q '"prompt_tokens": 123' target/cerberus/receipts/opencode.json
grep -q '"completion_tokens": 45' target/cerberus/receipts/opencode.json
grep -q '"cost_usd": 0.0042' target/cerberus/receipts/opencode.json
grep -q '"validation": {' target/cerberus/receipts/opencode.json
grep -q '"trusted_for_posting": true' target/cerberus/receipts/opencode.json
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

if [[ "${CERBERUS_LIVE_REVIEW_PR:-}" == "1" ]]; then
  : "${CERBERUS_LIVE_REVIEW_REPO:?set CERBERUS_LIVE_REVIEW_REPO=owner/name}"
  : "${CERBERUS_LIVE_REVIEW_NUMBER:?set CERBERUS_LIVE_REVIEW_NUMBER=<pull request number>}"
  live_out="target/cerberus/live-review-pr"
  live_mode=(--dry-run)
  if [[ "${CERBERUS_LIVE_REVIEW_POST:-}" == "1" ]]; then
    live_mode=(--post)
    if [[ -n "${CERBERUS_LIVE_REVIEW_GH_TOKEN_FILE:-}" && -n "${CERBERUS_LIVE_REVIEW_GH_TOKEN_ENV:-}" ]]; then
      echo "set only one of CERBERUS_LIVE_REVIEW_GH_TOKEN_FILE or CERBERUS_LIVE_REVIEW_GH_TOKEN_ENV" >&2
      exit 1
    elif [[ -n "${CERBERUS_LIVE_REVIEW_GH_TOKEN_FILE:-}" ]]; then
      live_mode+=(--gh-token-file "$CERBERUS_LIVE_REVIEW_GH_TOKEN_FILE")
    elif [[ -n "${CERBERUS_LIVE_REVIEW_GH_TOKEN_ENV:-}" ]]; then
      live_mode+=(--gh-token-env "$CERBERUS_LIVE_REVIEW_GH_TOKEN_ENV")
    else
      echo "live review posting requires CERBERUS_LIVE_REVIEW_GH_TOKEN_FILE or CERBERUS_LIVE_REVIEW_GH_TOKEN_ENV" >&2
      exit 1
    fi
  fi
  cargo run --locked -- review-pr \
    --number "$CERBERUS_LIVE_REVIEW_NUMBER" \
    --repo "$CERBERUS_LIVE_REVIEW_REPO" \
    --out-dir "$live_out" \
    --summary-target "${CERBERUS_LIVE_REVIEW_SUMMARY_TARGET:-status}" \
    --harness "${CERBERUS_LIVE_REVIEW_HARNESS:-opencode}" \
    "${live_mode[@]}"
fi
