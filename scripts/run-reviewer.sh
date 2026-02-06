#!/usr/bin/env bash
set -euo pipefail

perspective="${1:-}"
if [[ -z "$perspective" ]]; then
  echo "usage: run-reviewer.sh <perspective>" >&2
  exit 2
fi

# CERBERUS_ROOT must point to the action directory
if [[ -z "${CERBERUS_ROOT:-}" ]]; then
  echo "CERBERUS_ROOT not set" >&2
  exit 2
fi

config_file="${CERBERUS_ROOT}/defaults/config.yml"
agent_file="${CERBERUS_ROOT}/agents/${perspective}.yaml"

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

max_steps="${KIMI_MAX_STEPS:-25}"

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

CERBERUS_ROOT_PY="$CERBERUS_ROOT" python3 - <<'PY'
import json
import os
from pathlib import Path

cerberus_root = os.environ["CERBERUS_ROOT_PY"]
template_path = Path(cerberus_root) / "templates" / "review-prompt.md"
text = template_path.read_text()

# Read PR context from JSON file if available (action mode)
pr_context_file = os.environ.get("GH_PR_CONTEXT", "")
if pr_context_file and Path(pr_context_file).exists():
    ctx = json.loads(Path(pr_context_file).read_text())
    pr_title = ctx.get("title", "")
    pr_author = ctx.get("author", {})
    if isinstance(pr_author, dict):
        pr_author = pr_author.get("login", "")
    head_branch = ctx.get("headRefName", "")
    base_branch = ctx.get("baseRefName", "")
    pr_body = ctx.get("body", "") or ""
else:
    # Fallback to individual env vars (legacy mode)
    pr_title = os.environ.get("GH_PR_TITLE", "")
    pr_author = os.environ.get("GH_PR_AUTHOR", "")
    head_branch = os.environ.get("GH_HEAD_BRANCH", "")
    base_branch = os.environ.get("GH_BASE_BRANCH", "")
    pr_body = os.environ.get("GH_PR_BODY", "")

diff_text = Path(os.environ["PR_DIFF_FILE"]).read_text()

replacements = {
    "{{PR_TITLE}}": pr_title,
    "{{PR_AUTHOR}}": pr_author,
    "{{HEAD_BRANCH}}": head_branch,
    "{{BASE_BRANCH}}": base_branch,
    "{{PR_BODY}}": pr_body,
    "{{FILE_LIST}}": os.environ.get("PR_FILE_LIST", ""),
    "{{DIFF}}": diff_text,
}

for key, value in replacements.items():
    text = text.replace(key, value)

Path("/tmp/review-prompt.md").write_text(text)
PY

echo "Running reviewer: $reviewer_name ($perspective)"

# Rewrite system_prompt_path in agent YAML to absolute path
agent_dir="$(cd "$(dirname "$agent_file")" && pwd)"
tmp_agent="/tmp/${perspective}-agent.yaml"
sed "s|system_prompt_path: \./|system_prompt_path: ${agent_dir}/|" "$agent_file" > "$tmp_agent"

model="${KIMI_MODEL:-kimi-k2.5}"
base_url="${KIMI_BASE_URL:-https://api.moonshot.ai/v1}"

# Create temp config with model, provider, and step limit
cat > /tmp/kimi-config.toml <<TOML
default_model = "moonshot/${model}"

[models."moonshot/${model}"]
provider = "moonshot"
model = "${model}"
max_context_size = 262144
capabilities = ["thinking"]

[providers.moonshot]
type = "kimi"
base_url = "${base_url}"
api_key = "${KIMI_API_KEY}"

[loop_control]
max_steps_per_turn = ${max_steps}
TOML

echo "--- config ---"
sed 's/api_key = ".*"/api_key = "***"/' /tmp/kimi-config.toml
echo "---"

set +e
kimi --quiet --thinking \
  --agent-file "$tmp_agent" \
  --prompt "$(cat /tmp/review-prompt.md)" \
  --config-file /tmp/kimi-config.toml \
  > "/tmp/${perspective}-output.txt" 2> "/tmp/${perspective}-stderr.log"
exit_code=$?
set -e

# Always dump diagnostics for CI visibility
output_size=$(wc -c < "/tmp/${perspective}-output.txt" 2>/dev/null || echo "0")
echo "kimi exit=$exit_code output=${output_size} bytes"

if [[ "$exit_code" -ne 0 ]]; then
  echo "--- stderr ---" >&2
  cat "/tmp/${perspective}-stderr.log" >&2
fi

echo "--- output (last 40 lines) ---"
tail -40 "/tmp/${perspective}-output.txt"
echo "--- end output ---"

echo "$exit_code" > "/tmp/${perspective}-exitcode"
exit "$exit_code"
