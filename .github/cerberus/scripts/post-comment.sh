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

if [[ -z "${PR_NUMBER:-}" ]]; then
  echo "missing PR_NUMBER env var" >&2
  exit 2
fi

config_file=".github/cerberus/config.yml"
marker="<!-- cerberus:${perspective} -->"

reviewer_info="$(
  awk -v p="$perspective" '
    $1=="-" && $2=="name:" {name=$3}
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

case "$verdict" in
  PASS) verdict_emoji="✅" ;;
  WARN) verdict_emoji="⚠️" ;;
  FAIL) verdict_emoji="❌" ;;
  *) verdict_emoji="❔" ;;
esac

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

sha_short="$(git rev-parse --short HEAD)"

comment_file="/tmp/${perspective}-comment.md"
cat > "$comment_file" <<EOF
## ${verdict_emoji} ${reviewer_name} — ${reviewer_desc}
**Verdict: ${verdict_emoji} ${verdict}** | Confidence: ${confidence}

### Summary
${summary}

### Findings (${findings_count})
$(cat "$findings_file")

---
*Cerberus Council | ${sha_short} | Override: /council override sha=${sha_short} (reason required)*
${marker}
EOF

existing_id="$(
  gh pr view "$PR_NUMBER" --json comments -q ".comments[] | select(.body | contains(\"$marker\")) | .id" | head -1
)"

if [[ -n "$existing_id" ]]; then
  gh api "repos/${GITHUB_REPOSITORY}/issues/comments/${existing_id}" -X PATCH -f body="$(cat "$comment_file")" >/dev/null
else
  gh pr comment "$PR_NUMBER" --body-file "$comment_file" >/dev/null
fi
