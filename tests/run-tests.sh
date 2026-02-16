#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "${COVERAGE:-0}" = "1" ]; then
    # Enable coverage in Python subprocesses (scripts invoked via subprocess in tests).
    export COVERAGE_PROCESS_START="$PWD/.coveragerc"
    export COVERAGE_FILE="$PWD/.coverage"
    python3 -m pytest tests/ -v --cov=scripts --cov-report=term-missing "$@"
    # coverage combine exits 1 if there's nothing to combine; guard on the glob.
    if ls .coverage.* >/dev/null 2>&1; then
        python3 -m coverage combine
    fi
else
    python3 -m pytest tests/ -v "$@"
fi
