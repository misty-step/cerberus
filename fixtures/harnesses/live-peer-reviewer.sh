#!/bin/sh
set -eu

mode="${1:-}"
shift || true

case "$mode" in
  argv-success)
    prompt="${1:?argv-success requires rendered prompt argument}"
    ;;
  stdin-success)
    prompt="$(cat)"
    ;;
  malformed)
    printf '%s\n' 'not a Cerberus artifact'
    exit 0
    ;;
  fail)
    printf '%s\n' 'fixture live peer failed' >&2
    exit 42
    ;;
  sleep)
    sleep 5
    exit 0
    ;;
  *)
    printf '%s\n' "unknown mode: $mode" >&2
    exit 64
    ;;
esac

require_prompt() {
  pattern="$1"
  description="$2"
  if ! printf '%s' "$prompt" | grep -q "$pattern"; then
    printf '%s\n' "prompt does not contain expected $description" >&2
    exit 65
  fi
}

require_prompt 'ReviewerArtifact.v1' 'artifact contract'
require_prompt 'peer-runner-reviewer' 'reviewer id'
require_prompt 'request_id:' 'request id field'
require_prompt 'diff --git a/src/lib.rs b/src/lib.rs' 'diff body'

cat <<'TRANSCRIPT'
Fixture live peer transcript.

CERBERUS_REVIEWER_ARTIFACT_JSON_BEGIN
{
  "schema_version": "reviewer-artifact.v1",
  "reviewer_id": "peer-runner-reviewer",
  "perspective": "correctness",
  "model": "openrouter/test-model",
  "status": "completed",
  "verdict": "PASS",
  "summary": "Fixture live peer accepted the prompt and returned a valid artifact.",
  "findings": [],
  "coverage": {
    "files_reviewed": [
      "src/lib.rs"
    ],
    "files_with_findings": []
  },
  "usage": {
    "prompt_tokens": 18,
    "completion_tokens": 21
  },
  "cost_usd": 0.0
}
CERBERUS_REVIEWER_ARTIFACT_JSON_END
TRANSCRIPT
