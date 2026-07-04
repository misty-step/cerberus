#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -z "${CERBERUS_SMOKE_OPENROUTER_KEY:-}" ]]; then
  echo "::notice::CERBERUS_SMOKE_OPENROUTER_KEY is not set; skipping live OpenCode smoke"
  exit 0
fi

smoke_model="${CERBERUS_SMOKE_OPENROUTER_MODEL:-openrouter/z-ai/glm-5.2}"
opencode_binary="${CERBERUS_SMOKE_OPENCODE_BINARY:-opencode}"
timeout_seconds="${CERBERUS_SMOKE_TIMEOUT_SECONDS:-300}"
out_dir="${CERBERUS_SMOKE_OUT_DIR:-target/cerberus/live-opencode-smoke}"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

repo="$tmp_dir/repo"
mkdir -p "$repo"
git -C "$repo" init --quiet
git -C "$repo" config user.email "cerberus-smoke@example.invalid"
git -C "$repo" config user.name "Cerberus Smoke"
cp -R fixtures/live-smoke/base/. "$repo/"
git -C "$repo" add .
git -C "$repo" commit --quiet -m "base safe ratio"
base_sha="$(git -C "$repo" rev-parse HEAD)"
cp -R fixtures/live-smoke/head/. "$repo/"
git -C "$repo" add .
git -C "$repo" commit --quiet -m "introduce ratio regression"
head_sha="$(git -C "$repo" rev-parse HEAD)"

rm -rf "$out_dir"
mkdir -p "$out_dir"

OPENROUTER_API_KEY="$CERBERUS_SMOKE_OPENROUTER_KEY" cargo run --locked -- review-diff \
  --repo-path "$repo" \
  --base "$base_sha" \
  --head "$head_sha" \
  --title "Cerberus live OpenCode smoke fixture" \
  --description "Tiny committed fixture diff that removes a divide-by-zero guard." \
  --request-id "cerberus-live-opencode-smoke" \
  --repo "misty-step/cerberus-live-smoke" \
  --instruction "This is a scheduled live substrate smoke. Review the tiny diff and emit exactly one valid ReviewArtifact.v1. A WARN or PASS verdict is acceptable; the smoke validates substrate contract compatibility, not reviewer quality." \
  --harness opencode \
  --opencode-binary "$opencode_binary" \
  --model "$smoke_model" \
  --allow-env OPENROUTER_API_KEY \
  --timeout-seconds "$timeout_seconds" \
  --out "$out_dir/artifact.json" \
  --markdown "$out_dir/review.md" \
  > "$out_dir/stdout.md" \
  2> "$out_dir/stderr.txt"

test -s "$out_dir/artifact.json"
test -s "$out_dir/review.md"
