#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH='' cd -- "${SCRIPT_DIR}/.." && pwd)
REPO_ROOT=$(CDPATH='' cd -- "${PROJECT_ROOT}/.." && pwd)

cd "${PROJECT_ROOT}"

MIX_ENV=prod mix release cerberus --overwrite

RELEASE_ROOT="${PROJECT_ROOT}/_build/prod/rel/cerberus"

[ -d "${RELEASE_ROOT}" ]

cmp -s "${RELEASE_ROOT}/repo/defaults/config.yml" "${REPO_ROOT}/defaults/config.yml"
cmp -s "${RELEASE_ROOT}/repo/pi/agents/correctness.md" "${REPO_ROOT}/pi/agents/correctness.md"
cmp -s "${RELEASE_ROOT}/repo/templates/review-prompt.md" "${REPO_ROOT}/templates/review-prompt.md"

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
