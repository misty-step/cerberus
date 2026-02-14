#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "${COVERAGE:-0}" = "1" ]; then
    python3 -m pytest tests/ -v --cov=scripts --cov-report=term-missing "$@"
else
    python3 -m pytest tests/ -v "$@"
fi
