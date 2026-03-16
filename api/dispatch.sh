#!/usr/bin/env bash
# Thin Cerberus API dispatcher for GitHub Actions.
#
# Preflight → POST /api/reviews → poll GET /api/reviews/:id → set outputs.
# All review execution happens server-side.

set -euo pipefail

# --- Helpers ---

parse_json() {
  # Extract a value from JSON using jq. Falls back to empty string on error.
  local filter="$1"
  jq -r "$filter // empty" 2>/dev/null || echo ""
}

# --- Preflight ---

if [ "$HEAD_REPO" != "$BASE_REPO" ]; then
  echo "::notice::Cerberus: skipping fork PR (no secrets available)"
  echo "verdict=SKIP" >> "$GITHUB_OUTPUT"
  echo "review-id=" >> "$GITHUB_OUTPUT"
  exit 0
fi

if [ "$IS_DRAFT" = "true" ]; then
  echo "::notice::Cerberus: skipping draft PR"
  echo "verdict=SKIP" >> "$GITHUB_OUTPUT"
  echo "review-id=" >> "$GITHUB_OUTPUT"
  exit 0
fi

if [ -z "${CERBERUS_API_KEY:-}" ]; then
  echo "::error::Cerberus: CERBERUS_API_KEY is not set"
  echo "verdict=SKIP" >> "$GITHUB_OUTPUT"
  echo "review-id=" >> "$GITHUB_OUTPUT"
  exit 1
fi

if [ -z "${CERBERUS_URL:-}" ]; then
  echo "::error::Cerberus: CERBERUS_URL is not set"
  exit 1
fi

if [ -z "${PR_NUMBER:-}" ] || [ -z "${HEAD_SHA:-}" ]; then
  echo "::error::Cerberus: PR_NUMBER or HEAD_SHA not available (is this a pull_request event?)"
  exit 1
fi

# --- Dispatch ---

REPO="${BASE_REPO}"
TIMEOUT="${CERBERUS_TIMEOUT:-600}"
POLL_INTERVAL="${CERBERUS_POLL_INTERVAL:-5}"
MAX_POLL_ERRORS=10

if ! [[ "$TIMEOUT" =~ ^[0-9]+$ ]]; then
  echo "::error::Cerberus: TIMEOUT must be a positive integer (got: ${TIMEOUT})"
  exit 1
fi
if ! [[ "$POLL_INTERVAL" =~ ^[0-9]+$ ]] || [ "$POLL_INTERVAL" -eq 0 ]; then
  echo "::error::Cerberus: POLL_INTERVAL must be a positive integer (got: ${POLL_INTERVAL})"
  exit 1
fi

payload=$(jq -n \
  --arg repo "$REPO" \
  --argjson pr_number "$PR_NUMBER" \
  --arg head_sha "$HEAD_SHA" \
  --arg github_token "$GITHUB_TOKEN" \
  --arg model "${CERBERUS_MODEL:-}" \
  '{repo: $repo, pr_number: $pr_number, head_sha: $head_sha, github_token: $github_token, model: $model}')

echo "Dispatching review for ${REPO}#${PR_NUMBER} (${HEAD_SHA:0:12})..."

response=$(curl -s -w "\n%{http_code}" \
  --connect-timeout 10 --max-time 30 \
  -X POST "${CERBERUS_URL}/api/reviews" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${CERBERUS_API_KEY}" \
  -d "$payload")

http_code=$(echo "$response" | tail -1)
body=$(echo "$response" | sed '$d')

if [ "$http_code" != "202" ]; then
  echo "::error::Cerberus API returned ${http_code}: ${body}"
  echo "verdict=SKIP" >> "$GITHUB_OUTPUT"
  echo "review-id=" >> "$GITHUB_OUTPUT"
  exit 1
fi

review_id=$(echo "$body" | parse_json '.review_id')
echo "Review dispatched: id=${review_id}"
echo "review-id=${review_id}" >> "$GITHUB_OUTPUT"

# --- Poll ---

elapsed=0
consecutive_errors=0

while [ "$elapsed" -lt "$TIMEOUT" ]; do
  sleep "$POLL_INTERVAL"
  elapsed=$((elapsed + POLL_INTERVAL))

  poll_response=$(curl -s -w "\n%{http_code}" \
    --connect-timeout 10 --max-time 30 \
    "${CERBERUS_URL}/api/reviews/${review_id}" \
    -H "Authorization: Bearer ${CERBERUS_API_KEY}")

  poll_code=$(echo "$poll_response" | tail -1)
  poll_body=$(echo "$poll_response" | sed '$d')

  if [ "$poll_code" != "200" ]; then
    consecutive_errors=$((consecutive_errors + 1))
    echo "::warning::Poll returned ${poll_code} (error ${consecutive_errors}/${MAX_POLL_ERRORS})"
    if [ "$consecutive_errors" -ge "$MAX_POLL_ERRORS" ]; then
      echo "::error::Too many consecutive poll errors, aborting"
      echo "verdict=SKIP" >> "$GITHUB_OUTPUT"
      exit 1
    fi
    continue
  fi
  consecutive_errors=0

  status=$(echo "$poll_body" | parse_json '.status // "unknown"')

  case "$status" in
    failed)
      echo "::error::Cerberus review pipeline failed (${elapsed}s)"
      echo "verdict=SKIP" >> "$GITHUB_OUTPUT"
      exit 1
      ;;
    completed)
      verdict=$(echo "$poll_body" | parse_json '.aggregated_verdict.verdict // "SKIP"')
      echo "Review complete: verdict=${verdict} (${elapsed}s)"
      echo "verdict=${verdict}" >> "$GITHUB_OUTPUT"

      # Write verdict JSON to RUNNER_TEMP for downstream consumption
      if [ -n "${RUNNER_TEMP:-}" ]; then
        verdict_path="${RUNNER_TEMP}/cerberus-api-verdict.json"
        echo "$poll_body" > "$verdict_path"
        echo "Verdict JSON written to ${verdict_path}"
      fi

      # Fail on FAIL verdict if configured
      if [ "${CERBERUS_FAIL_ON_VERDICT:-true}" = "true" ] && [ "$verdict" = "FAIL" ]; then
        echo "::error::Cerberus verdict: FAIL"
        exit 1
      fi

      exit 0
      ;;
    queued|running)
      echo "Status: ${status} (${elapsed}s elapsed)"
      ;;
    *)
      echo "::warning::Unknown status: ${status}"
      ;;
  esac
done

echo "::error::Cerberus review timed out after ${TIMEOUT}s"
echo "verdict=SKIP" >> "$GITHUB_OUTPUT"
exit 1
