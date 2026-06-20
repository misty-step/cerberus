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

cat fixtures/harness/pass-review.txt fixtures/harness/pass-review.txt \
  > target/cerberus/invalid-duplicate-artifacts.txt
artifact_json="$(awk '
  /-----BEGIN CERBERUS_REVIEW_ARTIFACT_V1-----/ { inside = 1; next }
  /-----END CERBERUS_REVIEW_ARTIFACT_V1-----/ { inside = 0 }
  inside { print }
' fixtures/harness/pass-review.txt)"
{
  cat fixtures/harness/pass-review.txt
  printf '\n<CERBERUS_REVIEW_ARTIFACT_V1>\n%s\n</CERBERUS_REVIEW_ARTIFACT_V1>\n' "$artifact_json"
} > target/cerberus/invalid-duplicate-marker-xml-artifacts.txt
{
  cat fixtures/harness/pass-review.txt
  printf '\n%s\n' "$artifact_json"
} > target/cerberus/invalid-duplicate-marker-raw-artifacts.txt
{
  printf '<CERBERUS_REVIEW_ARTIFACT_V1>\n%s\n</CERBERUS_REVIEW_ARTIFACT_V1>\n' "$artifact_json"
  printf '<CERBERUS_REVIEW_ARTIFACT_V1>\n%s\n</CERBERUS_REVIEW_ARTIFACT_V1>\n' "$artifact_json"
} > target/cerberus/invalid-duplicate-xml-artifacts.txt
{
  printf '<CERBERUS_REVIEW_ARTIFACT_V1>\n%s\n</CERBERUS_REVIEW_ARTIFACT_V1>\n' "$artifact_json"
  printf '%s\n' "$artifact_json"
} > target/cerberus/invalid-duplicate-xml-raw-artifacts.txt
printf '%s\n%s\n' "$artifact_json" "$artifact_json" \
  > target/cerberus/invalid-duplicate-raw-artifacts.txt
sed 's#{{context_capabilities}}#{"diff":true,"repo_head":false,"repo_base":true,"local_runtime":false,"remote_runtime":false,"external_research":"forbid"}#' \
  fixtures/harness/pass-review.txt \
  > target/cerberus/invalid-overstated-base.txt
sed 's#{{context_capabilities}}#{"diff":true,"repo_head":false,"repo_base":false,"local_runtime":true,"remote_runtime":false,"external_research":"forbid"}#' \
  fixtures/harness/pass-review.txt \
  > target/cerberus/invalid-overstated-runtime.txt
expect_review_failure duplicate-artifacts target/cerberus/invalid-duplicate-artifacts.txt
expect_review_failure duplicate-marker-xml-artifacts target/cerberus/invalid-duplicate-marker-xml-artifacts.txt
expect_review_failure duplicate-marker-raw-artifacts target/cerberus/invalid-duplicate-marker-raw-artifacts.txt
expect_review_failure duplicate-xml-artifacts target/cerberus/invalid-duplicate-xml-artifacts.txt
expect_review_failure duplicate-xml-raw-artifacts target/cerberus/invalid-duplicate-xml-raw-artifacts.txt
expect_review_failure duplicate-raw-artifacts target/cerberus/invalid-duplicate-raw-artifacts.txt
expect_review_failure overstated-base target/cerberus/invalid-overstated-base.txt
expect_review_failure overstated-runtime target/cerberus/invalid-overstated-runtime.txt
expect_review_failure unknown-finding-id fixtures/harness/invalid-unknown-finding-id.txt
expect_review_failure unknown-suggested-fix fixtures/harness/invalid-unknown-suggested-fix.txt
expect_review_failure orphan-suggested-fix fixtures/harness/invalid-orphan-suggested-fix.txt

grep -q 'expected exactly one ReviewArtifact.v1 candidate' target/cerberus/duplicate-artifacts.stderr
grep -q 'expected exactly one ReviewArtifact.v1 candidate' target/cerberus/duplicate-marker-xml-artifacts.stderr
grep -q 'expected exactly one ReviewArtifact.v1 candidate' target/cerberus/duplicate-marker-raw-artifacts.stderr
grep -q 'expected exactly one ReviewArtifact.v1 candidate' target/cerberus/duplicate-xml-artifacts.stderr
grep -q 'expected exactly one ReviewArtifact.v1 candidate' target/cerberus/duplicate-xml-raw-artifacts.stderr
grep -q 'expected exactly one ReviewArtifact.v1 candidate' target/cerberus/duplicate-raw-artifacts.stderr
grep -q 'artifact context capabilities overstate the request' target/cerberus/overstated-base.stderr
grep -q 'artifact context capabilities overstate the request' target/cerberus/overstated-runtime.stderr
grep -q 'references unknown finding id' target/cerberus/unknown-finding-id.stderr
grep -q 'references unknown suggested fix id' target/cerberus/unknown-suggested-fix.stderr
grep -q 'top-level suggested fix is not attached' target/cerberus/orphan-suggested-fix.stderr

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
CERBERUS_FAKE_GH_LOG=target/cerberus/review-pr-post-first-gh.log \
cargo run --locked -- review-pr \
  --number 7 \
  --repo example/fixture \
  --gh-binary "$fake_gh" \
  --harness fixture \
  --fixture-output fixtures/harness/valid-review.txt \
  --out-dir target/cerberus/review-pr-post-first \
  --summary-target check-run \
  --post

CERBERUS_FAKE_GH_STATE_DIR="$fake_gh_state" \
CERBERUS_FAKE_GH_LOG=target/cerberus/review-pr-post-second-gh.log \
cargo run --locked -- review-pr \
  --number 7 \
  --repo example/fixture \
  --gh-binary "$fake_gh" \
  --harness fixture \
  --fixture-output fixtures/harness/valid-review.txt \
  --out-dir target/cerberus/review-pr-post-second \
  --summary-target check-run \
  --post

CERBERUS_FAKE_GH_STATE_DIR="$fake_gh_state" \
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
  live_mode="--dry-run"
  if [[ "${CERBERUS_LIVE_REVIEW_POST:-}" == "1" ]]; then
    live_mode="--post"
  fi
  cargo run --locked -- review-pr \
    --number "$CERBERUS_LIVE_REVIEW_NUMBER" \
    --repo "$CERBERUS_LIVE_REVIEW_REPO" \
    --out-dir "$live_out" \
    --summary-target "${CERBERUS_LIVE_REVIEW_SUMMARY_TARGET:-status}" \
    --harness "${CERBERUS_LIVE_REVIEW_HARNESS:-opencode}" \
    $live_mode
fi
