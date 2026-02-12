#!/usr/bin/env bash
set -euo pipefail

perspective="${1:-}"
verdict_file="${2:-}"

if [[ -z "$perspective" || -z "$verdict_file" ]]; then
  echo "usage: post-comment.sh <perspective> <verdict-json>" >&2
  exit 2
fi
if [[ ! -f "$verdict_file" ]]; then
  echo "missing verdict file: $verdict_file" >&2
  exit 2
fi

if [[ -z "${CERBERUS_ROOT:-}" ]]; then
  echo "CERBERUS_ROOT not set" >&2
  exit 2
fi
config_file="${CERBERUS_ROOT}/defaults/config.yml"

if [[ -z "${PR_NUMBER:-}" ]]; then
  echo "missing PR_NUMBER env var" >&2
  exit 2
fi

marker="<!-- cerberus:${perspective} -->"

reviewer_info="$(
  awk -v p="$perspective" '
    $1=="-" && $2=="name:" {if (found) exit; name=$3}
    $1=="perspective:" && $2==p {found=1}
    found && $1=="description:" {
      desc=$0
      sub(/^[[:space:]]*description:[[:space:]]*/, "", desc)
      gsub(/^"|"$/, "", desc)
      print name "\t" desc
      exit
    }
  ' "$config_file"
)"

reviewer_name="${reviewer_info%%$'\t'*}"
reviewer_desc="${reviewer_info#*$'\t'}"

if [[ -z "$reviewer_name" ]]; then
  reviewer_name="${perspective^^}"
fi
if [[ "$reviewer_desc" == "$reviewer_info" ]]; then
  reviewer_desc="$perspective"
fi

verdict="$(jq -r .verdict "$verdict_file")"
confidence="$(jq -r .confidence "$verdict_file")"
summary="$(jq -r .summary "$verdict_file")"
model_used="$(jq -r '.model_used // empty' "$verdict_file")"
fallback_used="$(jq -r '.fallback_used // false' "$verdict_file")"
primary_model="$(jq -r '.primary_model // empty' "$verdict_file")"

if [[ "$verdict" == "null" || -z "$verdict" ]]; then
  echo "malformed verdict file: missing verdict field" >&2
  exit 2
fi
if [[ "$confidence" == "null" ]]; then confidence="?"; fi
if [[ "$summary" == "null" ]]; then summary="No summary available."; fi

case "$verdict" in
  PASS) verdict_emoji="✅" ;;
  WARN) verdict_emoji="⚠️" ;;
  FAIL) verdict_emoji="❌" ;;
  SKIP) verdict_emoji="⏭️" ;;
  *) verdict_emoji="❔" ;;
esac

# Detect SKIP reason for prominent banner using structured verdict fields
skip_banner=""
if [[ "$verdict" == "SKIP" ]]; then
  finding_category="$(jq -r '.findings[0].category // empty' "$verdict_file")"
  finding_title="$(jq -r '.findings[0].title // empty' "$verdict_file")"
  if [[ "$finding_category" == "api_error" ]]; then
    if printf '%s' "$finding_title" | grep -qiE "CREDITS_DEPLETED|QUOTA_EXCEEDED"; then
      skip_banner="> **⛔ API credits depleted.** This reviewer was skipped because the API provider has no remaining credits. Top up credits or configure a fallback provider."
    elif printf '%s' "$finding_title" | grep -qiE "KEY_INVALID"; then
      skip_banner="> **🔑 API key error.** This reviewer was skipped due to an authentication failure. Check that the API key is valid."
    else
      skip_banner="> **⚠️ API error.** This reviewer was skipped due to an API error."
    fi
  elif [[ "$finding_category" == "timeout" ]]; then
    skip_banner="> **⏱️ Timeout.** This reviewer exceeded the configured runtime limit."
  fi
fi

findings_file="/tmp/${perspective}-findings.md"
findings_count="$(
  VERDICT_FILE="$verdict_file" FINDINGS_FILE="$findings_file" python3 - <<'PY'
import json
import os

path = os.environ["VERDICT_FILE"]
out = os.environ["FINDINGS_FILE"]

data = json.load(open(path))
findings = data.get("findings", [])

sev = {
    "critical": "🔴",
    "major": "🟠",
    "minor": "🟡",
    "info": "🔵",
}

lines = []
for f in findings:
    emoji = sev.get(f.get("severity", "info"), "🔵")
    file = f.get("file", "unknown")
    line = f.get("line", 0)
    title = f.get("title", "Issue")
    desc = f.get("description", "")
    sugg = f.get("suggestion", "")
    lines.append(f"- {emoji} `{file}:{line}` — {title}. {desc} Suggestion: {sugg}")

if not lines:
    lines = ["- None"]

with open(out, "w") as fh:
    fh.write("\n".join(lines))

print(len(findings))
PY
)"

# Strip openrouter provider prefix for brevity: openrouter/moonshotai/kimi-k2.5 → kimi-k2.5
short_model() {
  local m="$1"
  m="${m#openrouter/}"  # remove openrouter/ prefix
  m="${m##*/}"          # keep only final segment
  echo "$m"
}

model_display=""
if [[ -n "$model_used" ]]; then
  short="$(short_model "$model_used")"
  if [[ "$fallback_used" == "true" && -n "$primary_model" ]]; then
    primary_short="$(short_model "$primary_model")"
    model_display=" | Model: \`${short}\` ↩️ (fallback from \`${primary_short}\`)"
  else
    model_display=" | Model: \`${short}\`"
  fi
fi

sha_short="$(git rev-parse --short HEAD)"

comment_file="/tmp/${perspective}-comment.md"
{
  printf '%s\n' "## ${verdict_emoji} ${reviewer_name} — ${reviewer_desc}"
  printf '%s\n' "**Verdict: ${verdict_emoji} ${verdict}** | Confidence: ${confidence}${model_display}"
  printf '\n'
  if [[ -n "$skip_banner" ]]; then
    printf '%s\n' "$skip_banner"
    printf '\n'
  fi
  printf '%s\n' "### Summary"
  printf '%s\n' "${summary}"
  printf '\n'
  printf '%s\n' "### Findings (${findings_count})"
  cat "$findings_file"
  printf '\n'
  printf '%s\n' "---"
  printf '%s\n' "*Cerberus Council | ${sha_short} | Override: /council override sha=${sha_short} (reason required)*"
  printf '%s\n' "${marker}"
} > "$comment_file"

python3 "$CERBERUS_ROOT/scripts/lib/github.py" \
  --repo "$GITHUB_REPOSITORY" \
  --pr "$PR_NUMBER" \
  --marker "$marker" \
  --body-file "$comment_file"
