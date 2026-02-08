#!/usr/bin/env bash
set -euo pipefail

perspective="${1:-}"
if [[ -z "$perspective" ]]; then
  echo "usage: run-reviewer.sh <perspective>" >&2
  exit 2
fi

trap 'rm -f "/tmp/${perspective}-kimi-config.toml" "/tmp/${perspective}-review-prompt.md" "/tmp/${perspective}-agent.yaml"' EXIT

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

stack_context="$(
  DIFF_FILE="$diff_file" python3 - <<'PY'
import json
import os
from pathlib import Path

diff_file = Path(os.environ["DIFF_FILE"])
changed_files = []
for line in diff_file.read_text(errors="ignore").splitlines():
    if line.startswith("diff --git "):
        parts = line.split()
        if len(parts) >= 4:
            path = parts[2]
            if path.startswith("a/"):
                path = path[2:]
            changed_files.append(path)
changed_files = sorted(set(changed_files))

ext_languages = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".java": "Java",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".cs": "C#",
    ".php": "PHP",
    ".sh": "Shell",
    ".yml": "YAML",
    ".yaml": "YAML",
}
languages = set()
for path in changed_files:
    suffix = Path(path).suffix.lower()
    if suffix in ext_languages:
        languages.add(ext_languages[suffix])
    if Path(path).name == "Dockerfile":
        languages.add("Dockerfile")

frameworks = set()
root = Path(".")

package_json = root / "package.json"
if package_json.exists():
    try:
        pkg = json.loads(package_json.read_text())
        deps = {}
        for key in ("dependencies", "devDependencies", "peerDependencies"):
            deps.update(pkg.get(key, {}) or {})
    except Exception:
        deps = {}
    if "next" in deps:
        frameworks.add("Next.js")
    elif "react" in deps:
        frameworks.add("React")
    if "vue" in deps:
        frameworks.add("Vue")
    if "svelte" in deps:
        frameworks.add("Svelte")
    if "express" in deps:
        frameworks.add("Express")
    if "fastify" in deps:
        frameworks.add("Fastify")

pyproject = root / "pyproject.toml"
if pyproject.exists():
    pyproject_text = pyproject.read_text(errors="ignore").lower()
    if "django" in pyproject_text:
        frameworks.add("Django")
    if "fastapi" in pyproject_text:
        frameworks.add("FastAPI")
    if "flask" in pyproject_text:
        frameworks.add("Flask")

if (root / "go.mod").exists():
    frameworks.add("Go modules")
if (root / "Cargo.toml").exists():
    frameworks.add("Rust/Cargo")
if (root / "Gemfile").exists():
    gemfile_text = (root / "Gemfile").read_text(errors="ignore").lower()
    if "rails" in gemfile_text:
        frameworks.add("Rails")
    else:
        frameworks.add("Ruby")
if (root / "pom.xml").exists() or (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
    frameworks.add("JVM")

parts = []
if languages:
    parts.append("Languages: " + ", ".join(sorted(languages)))
if frameworks:
    parts.append("Frameworks/runtime: " + ", ".join(sorted(frameworks)))

print(" | ".join(parts) if parts else "Unknown")
PY
)"

export PR_FILE_LIST="$file_list"
export PR_DIFF_FILE="$diff_file"
export PERSPECTIVE="$perspective"
export PR_STACK_CONTEXT="$stack_context"

CERBERUS_ROOT_PY="$CERBERUS_ROOT" PROMPT_OUTPUT="/tmp/${perspective}-review-prompt.md" python3 - <<'PY'
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
    "{{PROJECT_STACK}}": os.environ.get("PR_STACK_CONTEXT", "Unknown"),
    "{{DIFF}}": diff_text,
    "{{PERSPECTIVE}}": os.environ.get("PERSPECTIVE", ""),
}

for key, value in replacements.items():
    text = text.replace(key, value)

Path(os.environ["PROMPT_OUTPUT"]).write_text(text)
PY

echo "Running reviewer: $reviewer_name ($perspective)"

# Rewrite system_prompt_path in agent YAML to absolute path
agent_dir="$(cd "$(dirname "$agent_file")" && pwd)"
tmp_agent="/tmp/${perspective}-agent.yaml"
sed "s|system_prompt_path: \./|system_prompt_path: ${agent_dir}/|" "$agent_file" > "$tmp_agent"

model="${KIMI_MODEL:-kimi-k2.5}"
base_url="${KIMI_BASE_URL:-https://openrouter.ai/api/v1}"

# Create temp config with model, provider, and step limit
cat > "/tmp/${perspective}-kimi-config.toml" <<TOML
default_model = "openrouter/moonshotai/${model}"

[models."openrouter/moonshotai/${model}"]
provider = "openrouter"
model = "${model}"
max_context_size = 262144
capabilities = ["thinking"]

[providers.openrouter]
type = "kimi"
base_url = "${base_url}"
api_key = "${KIMI_API_KEY}"

[loop_control]
max_steps_per_turn = ${max_steps}
TOML

echo "--- config ---"
sed 's/api_key = ".*"/api_key = "***"/' "/tmp/${perspective}-kimi-config.toml"
echo "---"

review_timeout="${REVIEW_TIMEOUT:-600}"

# API error patterns to detect
# Permanent errors (not retryable): 401/402/403, bad key, quota exhaustion
# Transient errors (retryable): 429 (rate limit), 503 (service unavailable)
# Permanent checked first — non-recoverable errors should not waste retries.
detect_api_error() {
  local output_file="$1"
  local stderr_file="$2"

  # Combine output and stderr for error detection
  local combined
  combined="$(cat "$output_file" 2>/dev/null || echo "")$(cat "$stderr_file" 2>/dev/null || echo "")"

  # Check permanent errors first (not retryable, should not waste retry budget)
  # Patterns use error-context anchoring to avoid false positives on review prose.
  if echo "$combined" | grep -qiE "(incorrect_api_key|invalid_api_key|exceeded_current_quota|insufficient_quota|payment.required|quota.exceeded|credits.depleted|credits.exhausted)"; then
    echo "permanent"
    return
  fi
  if echo "$combined" | grep -qE "\"(status|code)\":\s*40[123]|error.*(401|402|403)|HTTP [45][0-9]{2}.*(auth|pay|quota|key)"; then
    echo "permanent"
    return
  fi

  # Check for transient errors (retryable)
  if echo "$combined" | grep -qiE "(rate.limit|too many requests|service.unavailable|temporarily.unavailable)"; then
    echo "transient"
    return
  fi
  if echo "$combined" | grep -qE "\"(status|code)\":\s*(429|503)|error.*(429|503)"; then
    echo "transient"
    return
  fi

  echo "none"
}

# Run kimi with retry logic for transient errors
max_retries=3
retry_count=0
backoff=5

while true; do
  set +e
  timeout "${review_timeout}" kimi --quiet --thinking \
    --agent-file "$tmp_agent" \
    --config-file "/tmp/${perspective}-kimi-config.toml" \
    < "/tmp/${perspective}-review-prompt.md" \
    > "/tmp/${perspective}-output.txt" 2> "/tmp/${perspective}-stderr.log"
  exit_code=$?
  set -e

  # Always dump diagnostics for CI visibility
  scratchpad="/tmp/${perspective}-review.md"
  stdout_file="/tmp/${perspective}-output.txt"
  output_size=$(wc -c < "$stdout_file" 2>/dev/null || echo "0")
  scratchpad_size=$(wc -c < "$scratchpad" 2>/dev/null || echo "0")
  echo "kimi exit=$exit_code stdout=${output_size} bytes scratchpad=${scratchpad_size} bytes (attempt $((retry_count + 1))/$((max_retries + 1)))"

  # Check for API errors
  error_type=$(detect_api_error "/tmp/${perspective}-output.txt" "/tmp/${perspective}-stderr.log")

  if [[ "$error_type" == "transient" ]] && [[ $retry_count -lt $max_retries ]]; then
    retry_count=$((retry_count + 1))
    echo "Transient API error detected (429/503). Retrying in ${backoff}s... (attempt $retry_count/$max_retries)"
    sleep "$backoff"
    backoff=$((backoff * 3))  # Exponential backoff: 5s, 15s, 45s
    continue
  fi

  # If it's a permanent error, write structured error JSON
  if [[ "$error_type" == "permanent" ]]; then
    echo "Permanent API error detected. Writing error verdict."

    # Preserve stderr for debugging before we override the output
    echo "--- stderr (permanent error) ---" >&2
    cat "/tmp/${perspective}-stderr.log" >&2 2>/dev/null || true
    echo "--- end stderr ---" >&2

    # Extract specific error message
    error_msg="$(cat "/tmp/${perspective}-output.txt" 2>/dev/null)$(cat "/tmp/${perspective}-stderr.log" 2>/dev/null)"

    # Determine specific error type for message
    error_type_str="API_ERROR"
    if echo "$error_msg" | grep -qiE "(incorrect_api_key|invalid_api_key|authentication|unauthorized)"; then
      error_type_str="API_KEY_INVALID"
    elif echo "$error_msg" | grep -qiE "(exceeded_current_quota|insufficient_quota|payment.required|quota.exceeded|credits.depleted|credits.exhausted)"; then
      error_type_str="API_CREDITS_DEPLETED"
    fi

    # Write structured error marker for parse-review.py
    cat > "/tmp/${perspective}-output.txt" <<EOF
API Error: $error_type_str

The Moonshot API returned an error that prevents the review from completing:

$error_msg

Please check your API key and quota settings.
EOF
    exit_code=0  # Mark as success so parse-review.py can handle it
  fi

  break
done

if [[ "$exit_code" -ne 0 ]]; then
  echo "--- stderr ---" >&2
  cat "/tmp/${perspective}-stderr.log" >&2
fi

# Scratchpad fallback chain: select best parse input
# 1. Timeout marker (when reviewer exceeded timeout)
# 2. Scratchpad with JSON block (primary)
# 3. Stdout with JSON block (fallback)
# 4. Scratchpad without JSON (partial review)
# 5. Stdout (triggers existing fallback)
timeout_marker="/tmp/${perspective}-timeout-marker.txt"
if [[ "$exit_code" -eq 124 ]]; then
  echo "::warning::${reviewer_name} (${perspective}) timed out after ${review_timeout}s"
  cat > "$timeout_marker" <<EOF
Review Timeout: timeout after ${review_timeout}s

${reviewer_name} (${perspective}) exceeded the configured timeout.
EOF
  parse_input="$timeout_marker"
  echo "parse-input: timeout marker"
  echo "timeout: forcing SKIP parse path"
  exit_code=0
else
  parse_input="$stdout_file"
  if [[ -f "$scratchpad" ]] && grep -q '```json' "$scratchpad" 2>/dev/null; then
    parse_input="$scratchpad"
    echo "parse-input: scratchpad (has JSON block)"
  elif [[ -s "$stdout_file" ]] && grep -q '```json' "$stdout_file" 2>/dev/null; then
    parse_input="$stdout_file"
    echo "parse-input: stdout (has JSON block)"
  elif [[ -f "$scratchpad" ]] && [[ -s "$scratchpad" ]]; then
    parse_input="$scratchpad"
    echo "parse-input: scratchpad (partial, no JSON block)"
  else
    echo "parse-input: stdout (fallback)"
  fi
fi

# Write selected parse input path for downstream steps
echo "$parse_input" > "/tmp/${perspective}-parse-input"

echo "--- output (last 40 lines) ---"
tail -40 "$parse_input"
echo "--- end output ---"

echo "$exit_code" > "/tmp/${perspective}-exitcode"
exit "$exit_code"
