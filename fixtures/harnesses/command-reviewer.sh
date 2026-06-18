#!/bin/sh
set -eu

mode="${1:-success}"
shift || true

child_marker=""
case "$mode" in
  spawn-child | spawn-ignore-term)
    child_marker="${1:?$mode requires a marker path}"
    shift
    ;;
esac

input=""
output=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --input)
      input="${2:?--input requires a value}"
      shift 2
      ;;
    --output)
      output="${2:?--output requires a value}"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 64
      ;;
  esac
done

if [ -z "$input" ] || [ -z "$output" ]; then
  echo "missing --input or --output" >&2
  exit 64
fi

require_input() {
  pattern="$1"
  description="$2"
  if ! grep -q "$pattern" "$input"; then
    echo "input does not contain expected $description" >&2
    exit 65
  fi
}

require_input '"request_id": "command-harness-request"' "request_id"
require_input '"id": "command-reviewer"' "reviewer id"
require_input '"head_sha": "command-harness-sha"' "head sha"
require_input 'CERBERUS_COMMAND_FINDING' "diff body"
require_input '"path": "src/lib.rs"' "changed file path"

case "$mode" in
  success)
    cat >"$output" <<'JSON'
{
  "schema_version": "reviewer-artifact.v1",
  "reviewer_id": "command-reviewer",
  "perspective": "command",
  "model": "fixture:model",
  "status": "completed",
  "verdict": "FAIL",
  "summary": "Command harness fixture emitted one finding.",
  "findings": [
    {
      "id": "command-fixture-finding",
      "reviewer_id": "command-reviewer",
      "perspective": "command",
      "severity": "major",
      "category": "fixture",
      "title": "Command harness finding",
      "description": "The command harness fixture emitted this finding.",
      "evidence": "CERBERUS_COMMAND_FINDING",
      "citation": {
        "path": "src/lib.rs",
        "line": 1
      },
      "confidence": 1.0
    }
  ],
  "coverage": {
    "files_reviewed": [
      "src/lib.rs"
    ],
    "files_with_findings": [
      "src/lib.rs"
    ]
  },
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 8
  },
  "cost_usd": 0.0,
  "degraded_reason": null
}
JSON
    ;;
  fail)
    echo "fixture command failed" >&2
    exit 42
    ;;
  noisy-fail)
    i=0
    while [ "$i" -lt 5000 ]; do
      printf x >&2
      i=$((i + 1))
    done
    exit 43
    ;;
  sleep)
    sleep 5
    ;;
  spawn-child)
    (
      sleep 0.2
      echo survived >"$child_marker"
    ) &
    wait
    ;;
  spawn-ignore-term)
    (
      trap '' TERM
      sleep 0.2
      echo survived >"$child_marker"
    ) &
    wait
    ;;
  *)
    echo "unknown mode: $mode" >&2
    exit 64
    ;;
esac
