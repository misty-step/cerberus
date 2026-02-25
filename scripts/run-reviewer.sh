#!/usr/bin/env bash
set -euo pipefail

perspective="${1:-}"
if [[ -z "$perspective" ]]; then
  echo "usage: run-reviewer.sh <perspective>" >&2
  exit 2
fi

if [[ -z "${CERBERUS_ROOT:-}" ]]; then
  echo "CERBERUS_ROOT not set" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
runner="${CERBERUS_ROOT}/scripts/run-reviewer.py"
if [[ ! -f "$runner" ]]; then
  runner="${script_dir}/run-reviewer.py"
fi

python3 "$runner" "$perspective"
