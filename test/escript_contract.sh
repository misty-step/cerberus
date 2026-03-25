#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH='' cd -- "${SCRIPT_DIR}/.." && pwd)

cd "${PROJECT_ROOT}"

mix escript.build

[ -x "${PROJECT_ROOT}/cerberus" ]

HELP_OUTPUT=$("${PROJECT_ROOT}/cerberus" --help 2>&1)
printf '%s\n' "${HELP_OUTPUT}" | grep -F "Usage:" >/dev/null
printf '%s\n' "${HELP_OUTPUT}" | grep -F "cerberus review --repo <path> --base <ref> --head <ref>" >/dev/null
printf '%s\n' "${HELP_OUTPUT}" | grep -F "Commands:" >/dev/null

REVIEW_HELP_OUTPUT=$("${PROJECT_ROOT}/cerberus" review --help 2>&1)
printf '%s\n' "${REVIEW_HELP_OUTPUT}" | grep -F "Usage:" >/dev/null
printf '%s\n' "${REVIEW_HELP_OUTPUT}" | grep -F -- "--repo <path> --base <ref> --head <ref>" >/dev/null

if printf '%s\n' "${REVIEW_HELP_OUTPUT}" | grep -F -- "--diff" >/dev/null; then
  echo "legacy --diff help should not be present"
  exit 1
fi

for retired in init start server migrate
do
  set +e
  RETIRED_OUTPUT=$("${PROJECT_ROOT}/cerberus" "${retired}" 2>&1)
  RETIRED_STATUS=$?
  set -e

  if [ "${RETIRED_STATUS}" -eq 0 ]; then
    echo "retired command unexpectedly succeeded: ${retired}"
    exit 1
  fi

  printf '%s\n' "${RETIRED_OUTPUT}" | grep -F "Command \`${retired}\` has been retired." >/dev/null
done
