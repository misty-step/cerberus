#!/usr/bin/env bash
set -euo pipefail

perspective="${1:-}"
if [[ -z "$perspective" ]]; then
  echo "usage: run-reviewer.sh <perspective>" >&2
  exit 2
fi

cerberus_staging_backup_dir=""
cerberus_staging_had_opencode_json=0
cerberus_staging_had_opencode_dir=0
cerberus_staging_had_agents_dir=0
cerberus_staging_had_agent_file=0
cerberus_staging_agent_dest=""

# shellcheck disable=SC2317,SC2329
# Invoked via `trap`.
cerberus_cleanup() {
  rm -f "/tmp/${perspective}-review-prompt.md" || true

  if [[ -z "$cerberus_staging_backup_dir" ]]; then
    return
  fi

  if [[ "$cerberus_staging_had_opencode_json" -eq 1 ]]; then
    cp "$cerberus_staging_backup_dir/opencode.json" "opencode.json"
  else
    rm -f "opencode.json"
  fi

  if [[ -n "$cerberus_staging_agent_dest" ]]; then
    if [[ "$cerberus_staging_had_agent_file" -eq 1 ]]; then
      cp "$cerberus_staging_backup_dir/agent.md" "$cerberus_staging_agent_dest"
    else
      rm -f "$cerberus_staging_agent_dest"
    fi
  fi

  if [[ "$cerberus_staging_had_agents_dir" -eq 0 ]]; then
    rmdir ".opencode/agents" 2>/dev/null || true
  fi
  if [[ "$cerberus_staging_had_opencode_dir" -eq 0 ]]; then
    rmdir ".opencode" 2>/dev/null || true
  fi

  rm -rf "$cerberus_staging_backup_dir" || true
}

trap cerberus_cleanup EXIT

# CERBERUS_ROOT must point to the action directory
if [[ -z "${CERBERUS_ROOT:-}" ]]; then
  echo "CERBERUS_ROOT not set" >&2
  exit 2
fi

config_file="${CERBERUS_ROOT}/defaults/config.yml"
agent_file="${CERBERUS_ROOT}/.opencode/agents/${perspective}.md"

if [[ ! -f "$agent_file" ]]; then
  echo "missing agent file: $agent_file" >&2
  exit 2
fi

# OpenCode discovers project config from the current working directory:
# - opencode.json
# - .opencode/agents/<agent>.md
#
# In GitHub Actions, composite actions execute in the consumer repo workspace
# ($GITHUB_WORKSPACE), not in $CERBERUS_ROOT. Stage Cerberus' OpenCode config
# into the workspace so `opencode run --agent <perspective>` uses trusted
# config + prompts, not repo-provided overrides. Restore the original workspace
# on exit to avoid surprising downstream steps.
stage_opencode_project_config() {
  local cerberus_root_abs
  cerberus_root_abs="$(cd "$CERBERUS_ROOT" && pwd -P)"

  # No staging needed when running directly inside the Cerberus repo.
  if [[ "$cerberus_root_abs" == "$(pwd -P)" ]]; then
    return
  fi

  case "$perspective" in
    (*/*|*..*) echo "invalid perspective: $perspective" >&2; exit 2 ;;
  esac

  if [[ ! -f "$CERBERUS_ROOT/opencode.json" ]]; then
    echo "missing opencode.json in CERBERUS_ROOT: $CERBERUS_ROOT/opencode.json" >&2
    exit 2
  fi

  if [[ -e "opencode.json" ]]; then
    if [[ -L "opencode.json" || ! -f "opencode.json" ]]; then
      echo "refusing to overwrite non-regular file: opencode.json" >&2
      exit 2
    fi
    cerberus_staging_had_opencode_json=1
  fi

  if [[ -e ".opencode" ]]; then
    if [[ -L ".opencode" || ! -d ".opencode" ]]; then
      echo "refusing to write into non-directory: .opencode" >&2
      exit 2
    fi
    cerberus_staging_had_opencode_dir=1
  fi

  if [[ -e ".opencode/agents" ]]; then
    if [[ -L ".opencode/agents" || ! -d ".opencode/agents" ]]; then
      echo "refusing to write into non-directory: .opencode/agents" >&2
      exit 2
    fi
    cerberus_staging_had_agents_dir=1
  fi

  cerberus_staging_agent_dest=".opencode/agents/${perspective}.md"
  if [[ -e "$cerberus_staging_agent_dest" ]]; then
    if [[ -L "$cerberus_staging_agent_dest" || ! -f "$cerberus_staging_agent_dest" ]]; then
      echo "refusing to overwrite non-regular file: $cerberus_staging_agent_dest" >&2
      exit 2
    fi
    cerberus_staging_had_agent_file=1
  fi

  cerberus_staging_backup_dir="$(mktemp -d "/tmp/cerberus-opencode-backup.XXXXXX")"

  if [[ "$cerberus_staging_had_opencode_json" -eq 1 ]]; then
    cp "opencode.json" "$cerberus_staging_backup_dir/opencode.json"
  fi
  if [[ "$cerberus_staging_had_agent_file" -eq 1 ]]; then
    cp "$cerberus_staging_agent_dest" "$cerberus_staging_backup_dir/agent.md"
  fi

  mkdir -p ".opencode/agents"
  cp "$CERBERUS_ROOT/opencode.json" "opencode.json"
  cp "$agent_file" "$cerberus_staging_agent_dest"

  echo "Staged Cerberus OpenCode config into workspace (restored on exit)." >&2
}

stage_opencode_project_config

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

DIFF_FILE="$diff_file" python3 - <<'PY'
import fnmatch
import os
import shlex
from pathlib import Path

diff_file = Path(os.environ["DIFF_FILE"])
original_diff = diff_file.read_text(errors="ignore")
lines = original_diff.splitlines(keepends=True)

prefix_lines = []
file_hunks = []
current_hunk = None

for line in lines:
    if line.startswith("diff --git "):
        if current_hunk is not None:
            file_hunks.append(current_hunk)
        current_hunk = [line]
        continue
    if current_hunk is None:
        prefix_lines.append(line)
    else:
        current_hunk.append(line)

if current_hunk is not None:
    file_hunks.append(current_hunk)

if not file_hunks:
    raise SystemExit(0)

skip_filenames = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Gemfile.lock",
    "Cargo.lock",
    "go.sum",
    "composer.lock",
    "poetry.lock",
}
skip_globs = ("*.generated.*", "*.min.js", "*.min.css")


def normalize_path(token: str) -> str:
    if token.startswith("a/") or token.startswith("b/"):
        return token[2:]
    return token


def extract_path(diff_header: str) -> str:
    try:
        parts = shlex.split(diff_header.strip())
    except ValueError:
        parts = diff_header.strip().split()
    if len(parts) < 4:
        return ""

    before_path = normalize_path(parts[2])
    after_path = normalize_path(parts[3])
    if after_path and after_path != "/dev/null":
        return after_path
    return before_path


def should_filter(path: str) -> bool:
    filename = Path(path).name
    if filename in skip_filenames:
        return True
    return any(fnmatch.fnmatch(filename, pattern) for pattern in skip_globs)


filtered_count = 0
filtered_hunks = []

for hunk in file_hunks:
    file_path = extract_path(hunk[0])
    if file_path and should_filter(file_path):
        filtered_count += 1
        continue
    filtered_hunks.append(hunk)

if filtered_count == 0:
    raise SystemExit(0)

if not filtered_hunks:
    print(
        f"Filtered {filtered_count} lockfile/generated files from diff "
        "(all files matched filter, keeping original diff)"
    )
    raise SystemExit(0)

filtered_diff = "".join(prefix_lines + [line for hunk in filtered_hunks for line in hunk])
diff_file.write_text(filtered_diff)
print(f"Filtered {filtered_count} lockfile/generated files from diff")
PY

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
    "{{CURRENT_DATE}}": __import__('datetime').date.today().isoformat(),
    "{{DIFF}}": diff_text,
    "{{PERSPECTIVE}}": os.environ.get("PERSPECTIVE", ""),
}

for key, value in replacements.items():
    text = text.replace(key, value)

Path(os.environ["PROMPT_OUTPUT"]).write_text(text)
PY

echo "Running reviewer: $reviewer_name ($perspective)"

model="${OPENCODE_MODEL:-openrouter/moonshotai/kimi-k2.5}"

review_timeout="${REVIEW_TIMEOUT:-600}"

# API error patterns to detect
# Permanent errors (not retryable): non-429 4xx, bad key/auth/quota failures
# Transient errors (retryable): 429 (rate limit), 5xx, and network transport errors
extract_retry_after_seconds() {
  local text="$1"
  local retry_after
  retry_after="$(
    printf "%s\n" "$text" \
      | grep -iEo 'retry[-_ ]after[" ]*[:=][ ]*[0-9]+' \
      | tail -n1 \
      | grep -Eo '[0-9]+' \
      | tail -n1 || true
  )"

  if [[ "$retry_after" =~ ^[0-9]+$ ]] && [[ "$retry_after" -gt 0 ]]; then
    echo "$retry_after"
  fi
}

detect_api_error() {
  local output_file="$1"
  local stderr_file="$2"

  DETECTED_ERROR_TYPE="none"
  DETECTED_ERROR_CLASS="none"
  DETECTED_RETRY_AFTER_SECONDS=""

  local combined
  combined="$(
    {
      cat "$output_file" 2>/dev/null || true
      printf '\n'
      cat "$stderr_file" 2>/dev/null || true
    }
  )"

  if echo "$combined" | grep -qiE "(incorrect_api_key|invalid_api_key|invalid.api.key|exceeded_current_quota|insufficient_quota|insufficient.credits|payment.required|quota.exceeded|credits.depleted|credits.exhausted)"; then
    DETECTED_ERROR_TYPE="permanent"
    DETECTED_ERROR_CLASS="auth_or_quota"
    return
  fi

  if echo "$combined" | grep -qiE "(rate.limit|too many requests|retry-after|\"(status|code)\"[[:space:]]*:[[:space:]]*429|http[^0-9]*429|error[^0-9]*429)"; then
    DETECTED_ERROR_TYPE="transient"
    DETECTED_ERROR_CLASS="rate_limit"
    DETECTED_RETRY_AFTER_SECONDS="$(extract_retry_after_seconds "$combined")"
    return
  fi

  if echo "$combined" | grep -qiE "(\"(status|code)\"[[:space:]]*:[[:space:]]*5[0-9]{2}|http[^0-9]*5[0-9]{2}|error[^0-9]*5[0-9]{2}|service.unavailable|temporarily.unavailable)"; then
    DETECTED_ERROR_TYPE="transient"
    DETECTED_ERROR_CLASS="server_5xx"
    return
  fi

  if echo "$combined" | grep -qiE "(network.*(error|timeout|unreachable)|timed out|timeout while|connection (reset|refused|aborted)|temporary failure|tls handshake timeout|econn(reset|refused)|enotfound|broken pipe|remote end closed connection)"; then
    DETECTED_ERROR_TYPE="transient"
    DETECTED_ERROR_CLASS="network"
    return
  fi

  if echo "$combined" | grep -qiE "(\"(status|code)\"[[:space:]]*:[[:space:]]*4([0-1][0-9]|2[0-8]|[3-9][0-9])|http[^0-9]*4([0-1][0-9]|2[0-8]|[3-9][0-9])|error[^0-9]*4([0-1][0-9]|2[0-8]|[3-9][0-9]))"; then
    DETECTED_ERROR_TYPE="permanent"
    DETECTED_ERROR_CLASS="client_4xx"
    return
  fi
}

default_backoff_seconds() {
  local retry_attempt="$1"
  case "$retry_attempt" in
    1) echo "2" ;;
    2) echo "4" ;;
    *) echo "8" ;;
  esac
}

# Run opencode with retry logic for transient errors
max_retries=3
retry_count=0

while true; do
  set +e
  OPENROUTER_API_KEY="${OPENROUTER_API_KEY}" \
  OPENCODE_DISABLE_AUTOUPDATE=true \
  timeout "${review_timeout}" opencode run \
    -m "${model}" \
    --agent "${perspective}" \
    < "/tmp/${perspective}-review-prompt.md" \
    > "/tmp/${perspective}-output.txt" 2> "/tmp/${perspective}-stderr.log"
  exit_code=$?
  set -e

  # Always dump diagnostics for CI visibility
  scratchpad="/tmp/${perspective}-review.md"
  stdout_file="/tmp/${perspective}-output.txt"
  output_size=$(wc -c < "$stdout_file" 2>/dev/null || echo "0")
  scratchpad_size="0"
  if [[ -f "$scratchpad" ]]; then
    scratchpad_size=$(wc -c < "$scratchpad" 2>/dev/null || echo "0")
  fi
  echo "opencode exit=$exit_code stdout=${output_size} bytes scratchpad=${scratchpad_size} bytes (attempt $((retry_count + 1))/$((max_retries + 1)))"

  if [[ "$exit_code" -eq 0 ]]; then
    break
  fi

  if [[ "$exit_code" -eq 124 ]]; then
    break
  fi

  detect_api_error "/tmp/${perspective}-output.txt" "/tmp/${perspective}-stderr.log"

  if [[ "$DETECTED_ERROR_TYPE" == "transient" ]] && [[ $retry_count -lt $max_retries ]]; then
    retry_count=$((retry_count + 1))
    wait_seconds="$(default_backoff_seconds "$retry_count")"
    if [[ "$DETECTED_ERROR_CLASS" == "rate_limit" ]] && [[ "$DETECTED_RETRY_AFTER_SECONDS" =~ ^[0-9]+$ ]] && [[ "$DETECTED_RETRY_AFTER_SECONDS" -gt 0 ]]; then
      wait_seconds="$DETECTED_RETRY_AFTER_SECONDS"
    fi
    echo "Retrying after transient error (class=${DETECTED_ERROR_CLASS}) attempt ${retry_count}/${max_retries}; wait=${wait_seconds}s"
    sleep "$wait_seconds"
    continue
  fi

  # If it's a permanent error, write structured error JSON
  if [[ "$DETECTED_ERROR_TYPE" == "permanent" ]]; then
    echo "Permanent API error detected. Writing error verdict."

    # Preserve stderr for debugging before we override the output
    echo "--- stderr (permanent error) ---" >&2
    cat "/tmp/${perspective}-stderr.log" >&2 2>/dev/null || true
    echo "--- end stderr ---" >&2

    # Extract specific error message
    error_msg="$(cat "/tmp/${perspective}-output.txt" 2>/dev/null)$(cat "/tmp/${perspective}-stderr.log" 2>/dev/null)"

    # Determine specific error type for message
    error_type_str="API_ERROR"
    if echo "$error_msg" | grep -qiE "(incorrect_api_key|invalid_api_key|invalid.api.key|authentication|unauthorized)"; then
      error_type_str="API_KEY_INVALID"
    elif echo "$error_msg" | grep -qiE "(exceeded_current_quota|insufficient_quota|insufficient.credits|payment.required|quota.exceeded|credits.depleted|credits.exhausted)"; then
      error_type_str="API_CREDITS_DEPLETED"
    fi

    # Write structured error marker for parse-review.py
    cat > "/tmp/${perspective}-output.txt" <<EOF
API Error: $error_type_str

The OpenRouter API returned an error that prevents the review from completing:

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
