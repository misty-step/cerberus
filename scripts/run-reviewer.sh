#!/usr/bin/env bash
set -euo pipefail

# Restrictive umask: temp files readable only by owner.
umask 077

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
  rm -f "/tmp/${perspective}-fast-path-prompt.md" || true
  # Note: fast-path-output.txt is NOT cleaned here — it may be the parse input
  # for downstream steps (same as primary output.txt and review.md).
  rm -f "/tmp/${perspective}-fast-path-stderr.log" || true
  rm -rf "${CERBERUS_ISOLATED_HOME:-}" 2>/dev/null || true

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

# Render prompt: PR metadata inline, diff by file reference
export PERSPECTIVE="$perspective"

CERBERUS_ROOT_PY="$CERBERUS_ROOT" \
  DIFF_FILE="$diff_file" \
  PROMPT_OUTPUT="/tmp/${perspective}-review-prompt.md" \
  python3 - <<'PY'
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
    pr_title = os.environ.get("GH_PR_TITLE", "")
    pr_author = os.environ.get("GH_PR_AUTHOR", "")
    head_branch = os.environ.get("GH_HEAD_BRANCH", "")
    base_branch = os.environ.get("GH_BASE_BRANCH", "")
    pr_body = os.environ.get("GH_PR_BODY", "")

replacements = {
    "{{PR_TITLE}}": pr_title,
    "{{PR_AUTHOR}}": pr_author,
    "{{HEAD_BRANCH}}": head_branch,
    "{{BASE_BRANCH}}": base_branch,
    "{{PR_BODY}}": pr_body,
    "{{DIFF_FILE}}": os.environ["DIFF_FILE"],
    "{{CURRENT_DATE}}": __import__('datetime').date.today().isoformat(),
    "{{PERSPECTIVE}}": os.environ.get("PERSPECTIVE", ""),
}

for key, value in replacements.items():
    text = text.replace(key, value)

Path(os.environ["PROMPT_OUTPUT"]).write_text(text)
PY

# Create an isolated HOME for the opencode process.  This confines any
# file writes (caches, config) to a disposable directory and keeps them
# away from the real runner HOME and workspace.
CERBERUS_ISOLATED_HOME="$(mktemp -d "/tmp/cerberus-home-${perspective}.XXXXXX")"
mkdir -p "${CERBERUS_ISOLATED_HOME}/.config" "${CERBERUS_ISOLATED_HOME}/.local/share" "${CERBERUS_ISOLATED_HOME}/tmp"
export CERBERUS_ISOLATED_HOME

echo "Running reviewer: $reviewer_name ($perspective)"

model="${OPENCODE_MODEL:-openrouter/moonshotai/kimi-k2.5}"

review_timeout="${REVIEW_TIMEOUT:-600}"

# Fast-path fallback: when the primary review times out with no output,
# run a stripped-down review with the diff inline (no tool calls needed).
# Budget: 20% of total timeout, capped at 120s; skip if total < 120s.
fast_path_budget=$(( review_timeout / 5 ))
if [[ $fast_path_budget -gt 120 ]]; then fast_path_budget=120; fi
if [[ $fast_path_budget -lt 60 ]]; then fast_path_budget=0; fi
primary_timeout="$review_timeout"
if [[ $fast_path_budget -gt 0 ]]; then
  primary_timeout=$(( review_timeout - fast_path_budget ))
fi

# Extract changed file paths from a unified diff.
extract_diff_files() {
  grep -E '^diff --git' "$1" 2>/dev/null \
    | sed 's|diff --git a/.* b/||' \
    | sort -u \
    | head -20 \
    || true
}

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

  if echo "$combined" | grep -qiE "(incorrect_api_key|invalid_api_key|invalid.api.key|exceeded_current_quota|insufficient_quota|insufficient.credits|payment.required|quota.exceeded|credits.depleted|credits.exhausted|no.cookie.auth|no.*credentials.*found|no.*auth.*credentials)"; then
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
  # Run opencode with a sanitized environment.  Only explicitly-allowed
  # variables are forwarded.  This prevents the model/CLI from seeing
  # GITHUB_TOKEN, GH_TOKEN, ACTIONS_RUNTIME_TOKEN, or any other
  # secrets that leak via the Actions runner environment.
  env -i \
    PATH="${PATH}" \
    HOME="${CERBERUS_ISOLATED_HOME}" \
    XDG_CONFIG_HOME="${CERBERUS_ISOLATED_HOME}/.config" \
    XDG_DATA_HOME="${CERBERUS_ISOLATED_HOME}/.local/share" \
    TMPDIR="${CERBERUS_ISOLATED_HOME}/tmp" \
    OPENROUTER_API_KEY="${OPENROUTER_API_KEY}" \
    OPENCODE_DISABLE_AUTOUPDATE=true \
    ${OPENCODE_MAX_STEPS:+OPENCODE_MAX_STEPS="${OPENCODE_MAX_STEPS}"} \
    ${OPENCODE_CAPTURE_PATH:+OPENCODE_CAPTURE_PATH="${OPENCODE_CAPTURE_PATH}"} \
  timeout "${primary_timeout}" opencode run \
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

# Parse input selection:
# - Primary: any file containing a ```json block (scratchpad first, then stdout)
# - Fallback: partial scratchpad/stdout (lets parse-review.py emit a partial verdict)
# - Timeout marker only when timed out AND no output exists to salvage
timeout_marker="/tmp/${perspective}-timeout-marker.txt"
if [[ "$exit_code" -eq 124 ]]; then
  echo "::warning::${reviewer_name} (${perspective}) timed out after ${review_timeout}s"
  # Try to salvage output before falling back to SKIP
  if [[ -f "$scratchpad" ]] && grep -q '```json' "$scratchpad" 2>/dev/null; then
    parse_input="$scratchpad"
    echo "parse-input: scratchpad (timeout, but has JSON block)"
  elif [[ -s "$stdout_file" ]] && grep -q '```json' "$stdout_file" 2>/dev/null; then
    parse_input="$stdout_file"
    echo "parse-input: stdout (timeout, but has JSON block)"
  elif [[ -f "$scratchpad" ]] && [[ -s "$scratchpad" ]]; then
    parse_input="$scratchpad"
    echo "parse-input: scratchpad (timeout, partial review)"
  elif [[ -s "$stdout_file" ]]; then
    parse_input="$stdout_file"
    echo "parse-input: stdout (timeout, partial review)"
  else
    # No salvageable output — attempt fast-path fallback review.
    diff_files="$(extract_diff_files "$diff_file")"
    fast_path_attempted="no"

    if [[ $fast_path_budget -gt 0 ]] && [[ -f "${CERBERUS_ROOT}/templates/fast-path-prompt.md" ]]; then
      fast_path_attempted="yes"
      echo "Primary review timed out with no output. Running fast-path fallback (${fast_path_budget}s)..."

      # Read diff content for inlining (truncate at 50 KB to stay within token limits).
      diff_content="$(head -c 51200 "$diff_file" 2>/dev/null || true)"
      diff_byte_count=$(wc -c < "$diff_file" 2>/dev/null || echo "0")
      if [[ "$diff_byte_count" -gt 51200 ]]; then
        diff_content="${diff_content}
... (truncated, ${diff_byte_count} bytes total)"
      fi

      # Render fast-path prompt with inline diff via Python (safe for special chars).
      CERBERUS_ROOT_PY="$CERBERUS_ROOT" \
        FP_PERSPECTIVE="$perspective" \
        FP_REVIEWER_NAME="$reviewer_name" \
        FP_DIFF_CONTENT="$diff_content" \
        FP_OUTPUT="/tmp/${perspective}-fast-path-prompt.md" \
        python3 -c "
import os; from pathlib import Path
tpl = (Path(os.environ['CERBERUS_ROOT_PY']) / 'templates' / 'fast-path-prompt.md').read_text()
for k, v in [('{{PERSPECTIVE}}', os.environ['FP_PERSPECTIVE']),
             ('{{REVIEWER_NAME}}', os.environ['FP_REVIEWER_NAME']),
             ('{{DIFF_CONTENT}}', os.environ['FP_DIFF_CONTENT'])]:
    tpl = tpl.replace(k, v)
Path(os.environ['FP_OUTPUT']).write_text(tpl)
"

      set +e
      env -i \
        PATH="${PATH}" \
        HOME="${CERBERUS_ISOLATED_HOME}" \
        XDG_CONFIG_HOME="${CERBERUS_ISOLATED_HOME}/.config" \
        XDG_DATA_HOME="${CERBERUS_ISOLATED_HOME}/.local/share" \
        TMPDIR="${CERBERUS_ISOLATED_HOME}/tmp" \
        OPENROUTER_API_KEY="${OPENROUTER_API_KEY}" \
        OPENCODE_DISABLE_AUTOUPDATE=true \
        OPENCODE_MAX_STEPS=1 \
      timeout "${fast_path_budget}" opencode run \
        -m "${model}" \
        --agent "${perspective}" \
        < "/tmp/${perspective}-fast-path-prompt.md" \
        > "/tmp/${perspective}-fast-path-output.txt" 2> "/tmp/${perspective}-fast-path-stderr.log"
      fast_path_exit=$?
      set -e

      fp_size=$(wc -c < "/tmp/${perspective}-fast-path-output.txt" 2>/dev/null || echo "0")
      echo "fast-path exit=$fast_path_exit stdout=${fp_size} bytes"

      if [[ "$fast_path_exit" -eq 0 ]] && grep -q '```json' "/tmp/${perspective}-fast-path-output.txt" 2>/dev/null; then
        parse_input="/tmp/${perspective}-fast-path-output.txt"
        echo "parse-input: fast-path output (has JSON block)"
      fi
    fi

    # If we still have no parse_input (fast-path skipped, failed, or produced no JSON),
    # write an enriched timeout marker with file list and diagnostics.
    if [[ -z "${parse_input:-}" ]]; then
      cat > "$timeout_marker" <<MARKER
Review Timeout: timeout after ${review_timeout}s
${reviewer_name} (${perspective}) exceeded the configured timeout.
Fast-path: ${fast_path_attempted}
Files in diff: ${diff_files}
Next steps: Increase timeout, reduce diff size, or check model provider status.
MARKER
      parse_input="$timeout_marker"
      echo "parse-input: timeout marker (no output to salvage)"
    fi
  fi
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
