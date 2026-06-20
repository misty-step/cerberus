#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

cargo fmt --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --locked

cargo run --locked -- review --help > target/cerberus-review-help.txt
grep -q '\[default: opencode\]' target/cerberus-review-help.txt
grep -q 'possible values: opencode, omp, fixture' target/cerberus-review-help.txt
cargo run --locked -- request --help > target/cerberus-request-help.txt
grep -q 'git-range' target/cerberus-request-help.txt
grep -q 'pr' target/cerberus-request-help.txt

rm -rf target/cerberus
mkdir -p target/cerberus

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

cargo run --locked -- request git-range \
  --repo-path "$tmp_repo" \
  --base "$base_sha" \
  --head "$head_sha" \
  --instruction "Exercise generated git-range request review." \
  --out target/cerberus/git-range-request.json

grep -q '"kind": "git_range"' target/cerberus/git-range-request.json
cargo run --locked -- review \
  --request target/cerberus/git-range-request.json \
  --harness fixture \
  --fixture-output fixtures/harness/valid-review.txt \
  --out target/cerberus/git-range-artifact.json \
  --markdown target/cerberus/git-range-review.md \
  --execution-plan target/cerberus/git-range-execution_plan.json

GH_TOKEN=should-not-leak cargo run --locked -- review \
  --request target/cerberus/git-range-request.json \
  --harness opencode \
  --opencode-binary "$PWD/fixtures/bin/fake-opencode" \
  --out target/cerberus/git-range-opencode-artifact.json \
  --markdown target/cerberus/git-range-opencode-review.md \
  --execution-plan target/cerberus/git-range-opencode-execution_plan.json \
  --transcript target/cerberus/git-range-opencode-transcript.txt

cargo run --locked -- review \
  --request fixtures/requests/diff-only.json \
  --harness fixture \
  --fixture-output fixtures/harness/valid-review.txt \
  --out target/cerberus/artifact.json \
  --markdown target/cerberus/review.md \
  --execution-plan target/cerberus/execution_plan.json \
  --transcript target/cerberus/transcript.txt

cargo run --locked -- render \
  --artifact target/cerberus/artifact.json \
  --markdown target/cerberus/review-rendered.md

GH_TOKEN=should-not-leak cargo run --locked -- review \
  --request fixtures/requests/diff-only.json \
  --harness opencode \
  --opencode-binary "$PWD/fixtures/bin/fake-opencode" \
  --out target/cerberus/opencode-artifact.json \
  --markdown target/cerberus/opencode-review.md \
  --execution-plan target/cerberus/opencode-execution_plan.json \
  --transcript target/cerberus/opencode-transcript.txt

GH_TOKEN=should-not-leak cargo run --locked -- review \
  --request fixtures/requests/diff-only.json \
  --harness omp \
  --omp-binary "$PWD/fixtures/bin/fake-omp" \
  --out target/cerberus/omp-artifact.json \
  --markdown target/cerberus/omp-review.md \
  --execution-plan target/cerberus/omp-execution_plan.json \
  --transcript target/cerberus/omp-transcript.txt

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
test -s target/cerberus/opencode-artifact.json
test -s target/cerberus/opencode-execution_plan.json
test -s target/cerberus/opencode-transcript.txt
test -s target/cerberus/omp-artifact.json
test -s target/cerberus/omp-execution_plan.json
test -s target/cerberus/omp-transcript.txt

grep -q '"private_material_in_argv": false' target/cerberus/execution_plan.json
grep -q '"diff": true' target/cerberus/artifact.json
grep -q '"repo_head": false' target/cerberus/artifact.json
grep -q '"repo_head": true' target/cerberus/git-range-artifact.json
grep -q '"repo_head": true' target/cerberus/git-range-opencode-artifact.json
grep -q '"workspace_mode": "repo_head_worktree"' target/cerberus/git-range-opencode-execution_plan.json
grep -q 'Cerberus Review: WARN' target/cerberus/review.md
grep -q '"harness": "opencode"' target/cerberus/opencode-execution_plan.json
grep -q '"harness": "omp"' target/cerberus/omp-execution_plan.json
grep -q '"workspace_mode": "diff_packet"' target/cerberus/opencode-execution_plan.json
grep -q '"workspace_mode": "diff_packet"' target/cerberus/omp-execution_plan.json
grep -q '<prompt-file>' target/cerberus/opencode-execution_plan.json
grep -q '<request-file>' target/cerberus/opencode-execution_plan.json
grep -q '<prompt-file>' target/cerberus/git-range-opencode-execution_plan.json
grep -q '<request-file>' target/cerberus/git-range-opencode-execution_plan.json
grep -q '<prompt-file>' target/cerberus/omp-execution_plan.json
