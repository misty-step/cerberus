#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH='' cd -- "${SCRIPT_DIR}/.." && pwd)
REPO_ROOT=$(CDPATH='' cd -- "${PROJECT_ROOT}/.." && pwd)
SERVER_PID=''

cleanup() {
  if [ -n "${SERVER_PID}" ]; then
    kill "${SERVER_PID}" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT HUP INT TERM

cd "${PROJECT_ROOT}"

MIX_ENV=prod mix release cerberus --overwrite

RELEASE_ROOT="${PROJECT_ROOT}/_build/prod/rel/cerberus"

[ -d "${RELEASE_ROOT}" ]

diff -qr "${RELEASE_ROOT}/repo/defaults" "${REPO_ROOT}/defaults" >/dev/null
diff -qr "${RELEASE_ROOT}/repo/pi/agents" "${REPO_ROOT}/pi/agents" >/dev/null
diff -qr "${RELEASE_ROOT}/repo/templates" "${REPO_ROOT}/templates" >/dev/null

sh -n "${RELEASE_ROOT}/bin/server"
sh -n "${RELEASE_ROOT}/bin/migrate"

MIGRATE_OUTPUT=$(
  CERBERUS_API_KEY=test CERBERUS_REPO_ROOT='' CERBERUS_DB_PATH='' \
    "${RELEASE_ROOT}/bin/migrate" 2>&1
)

printf '%s\n' "${MIGRATE_OUTPUT}" | grep -F "No database migrations configured for cerberus_elixir" >/dev/null

EVAL_OUTPUT=$(
  CERBERUS_API_KEY=test CERBERUS_REPO_ROOT='' CERBERUS_DB_PATH='' \
    "${RELEASE_ROOT}/bin/cerberus" eval \
      'IO.puts("REPO_ROOT=" <> System.fetch_env!("CERBERUS_REPO_ROOT")); IO.puts("REPO_DIR_EXISTS=" <> to_string(File.dir?(System.fetch_env!("CERBERUS_REPO_ROOT")))); IO.puts("DB_PATH=" <> System.fetch_env!("CERBERUS_DB_PATH")); IO.puts("DB_DIR_EXISTS=" <> to_string(File.dir?(Path.dirname(System.fetch_env!("CERBERUS_DB_PATH")))))' \
      2>&1
)

printf '%s\n' "${EVAL_OUTPUT}" | grep -F "REPO_ROOT=${RELEASE_ROOT}/repo" >/dev/null
printf '%s\n' "${EVAL_OUTPUT}" | grep -F "REPO_DIR_EXISTS=true" >/dev/null
printf '%s\n' "${EVAL_OUTPUT}" | grep -F "DB_PATH=${RELEASE_ROOT}/data/cerberus.sqlite3" >/dev/null
printf '%s\n' "${EVAL_OUTPUT}" | grep -F "DB_DIR_EXISTS=true" >/dev/null

PORT=8081 CERBERUS_API_KEY=test CERBERUS_REPO_ROOT='' CERBERUS_DB_PATH='' \
  "${RELEASE_ROOT}/bin/server" >/tmp/cerberus-release-contract.log 2>&1 &
SERVER_PID=$!

i=0
until curl -fsS "http://127.0.0.1:8081/api/health" >/tmp/cerberus-release-contract-health.json 2>/dev/null
do
  i=$((i + 1))

  if [ "${i}" -ge 30 ]; then
    cat /tmp/cerberus-release-contract.log
    exit 1
  fi

  sleep 1
done

grep -F '{"status":"ok"}' /tmp/cerberus-release-contract-health.json >/dev/null
