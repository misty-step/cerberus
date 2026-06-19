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
  file-success)
    prompt_path="${1:?file-success requires prompt file path}"
    prompt="$(cat "$prompt_path")"
    prompt_mode="$(
      stat -f '%Lp' "$prompt_path" 2>/dev/null ||
        stat -c '%a' "$prompt_path" 2>/dev/null
    )"
    if [ "$prompt_mode" != "600" ] && [ "$prompt_mode" != "0600" ]; then
      printf '%s\n' "prompt file mode is not private: $prompt_mode" >&2
      exit 66
    fi
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

extract_prompt_field() {
  field="$1"
  printf '%s\n' "$prompt" | sed -n "s/^- ${field}: //p" | sed -n '1p'
}

reviewer_id="$(extract_prompt_field id)"
perspective="$(extract_prompt_field perspective)"
model="$(extract_prompt_field model)"
if [ -z "$reviewer_id" ] || [ -z "$perspective" ] || [ -z "$model" ]; then
  printf '%s\n' 'prompt does not contain reviewer metadata' >&2
  exit 65
fi

require_prompt 'ReviewerArtifact.v1' 'artifact contract'
require_prompt 'Reviewer:' 'reviewer section'
require_prompt 'request_id:' 'request id field'
require_prompt 'diff --git a/src/lib.rs b/src/lib.rs' 'diff body'

if [ "${prompt_path:-}" ]; then
  printf 'PROMPT_FILE=%s\n' "$prompt_path"
  printf 'PROMPT_FILE_MODE=%s\n' "$prompt_mode"
fi

cat <<'TRANSCRIPT'
Fixture live peer transcript.

CERBERUS_REVIEWER_ARTIFACT_JSON_BEGIN
TRANSCRIPT
cat <<TRANSCRIPT
{
  "schema_version": "reviewer-artifact.v1",
  "reviewer_id": "$reviewer_id",
  "perspective": "$perspective",
  "model": "$model",
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
