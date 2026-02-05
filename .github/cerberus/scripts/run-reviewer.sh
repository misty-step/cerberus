#!/usr/bin/env bash
set -euo pipefail

perspective="${1:-}"
if [[ -z "$perspective" ]]; then
  echo "usage: run-reviewer.sh <perspective>" >&2
  exit 2
fi

config_file=".github/cerberus/config.yml"
template_file=".github/cerberus/templates/review-prompt.md"
agent_file=".github/cerberus/agents/${perspective}.yaml"

if [[ ! -f "$agent_file" ]]; then
  echo "missing agent file: $agent_file" >&2
  exit 2
fi

reviewer_name="$(
  awk -v p="$perspective" '
    $1=="-" && $2=="name:" {name=$3}
    $1=="perspective:" && $2==p {print name; exit}
  ' "$config_file"
)"
if [[ -z "$reviewer_name" ]]; then
  echo "unknown perspective in config: $perspective" >&2
  exit 2
fi

max_steps="$(
  awk '/max_steps:/ {print $2; exit}' "$config_file" || true
)"
if [[ -z "$max_steps" ]]; then
  max_steps="25"
fi

diff_file=""
if [[ -n "${GH_DIFF_FILE:-}" && -f "${GH_DIFF_FILE:-}" ]]; then
  diff_file="$GH_DIFF_FILE"
elif [[ -n "${GH_DIFF:-}" ]]; then
  diff_file="/tmp/pr.diff"
  printf "%s" "$GH_DIFF" > "$diff_file"
else
  echo "missing diff input (GH_DIFF or GH_DIFF_FILE)" >&2
  exit 2
fi

file_list="$(grep -E '^diff --git' "$diff_file" | awk '{print $3}' | sed 's|^a/||' | sort -u || true)"
if [[ -z "$file_list" ]]; then
  file_list="(none)"
else
  file_list="$(printf "%s\n" "$file_list" | sed 's/^/- /')"
fi

export PR_FILE_LIST="$file_list"
export PR_DIFF_FILE="$diff_file"

python3 - <<'PY'
import os
from pathlib import Path

template_path = Path(".github/cerberus/templates/review-prompt.md")
text = template_path.read_text()

def val(name: str) -> str:
    return os.environ.get(name, "")

diff_text = Path(os.environ["PR_DIFF_FILE"]).read_text()

replacements = {
    "{{PR_TITLE}}": val("GH_PR_TITLE"),
    "{{PR_AUTHOR}}": val("GH_PR_AUTHOR"),
    "{{HEAD_BRANCH}}": val("GH_HEAD_BRANCH"),
    "{{BASE_BRANCH}}": val("GH_BASE_BRANCH"),
    "{{PR_BODY}}": val("GH_PR_BODY"),
    "{{FILE_LIST}}": os.environ.get("PR_FILE_LIST", ""),
    "{{DIFF}}": diff_text,
}

for key, value in replacements.items():
    text = text.replace(key, value)

Path("/tmp/review-prompt.md").write_text(text)
PY

echo "Running reviewer: $reviewer_name ($perspective)"

set +e
kimi --print --thinking \
  --agent-file "$agent_file" \
  --prompt "$(cat /tmp/review-prompt.md)" \
  --output-format stream-json \
  --max-steps-per-turn "$max_steps" \
  > "/tmp/${perspective}-output.jsonl"
exit_code=$?
set -e

echo "$exit_code" > "/tmp/${perspective}-exitcode"
exit "$exit_code"
