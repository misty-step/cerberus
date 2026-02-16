"""Coverage hook for Python subprocesses executed from ./scripts.

Why this file exists:
- Many tests execute scripts in this directory via subprocess (sys.executable + path/to/script).
- pytest-cov measures the parent test process, but child Python processes need an explicit
  coverage auto-start hook.

How it works:
- Python imports `sitecustomize` automatically at startup (unless -S).
- When running a script from this directory, `sys.path[0]` is this directory, so this module
  is importable without touching PYTHONPATH.
- If COVERAGE_PROCESS_START is set (exported by our test runners), we start coverage via
  coverage.process_startup(), which honors .coveragerc and writes parallel data files.
"""

import os


def _maybe_start_coverage() -> None:
    if not os.environ.get("COVERAGE_PROCESS_START"):
        return
    try:
        import coverage
    except ImportError:
        return

    try:
        coverage.process_startup()
    except Exception:
        # Never break the subprocess if coverage is misconfigured.
        # Our smoke test should catch regressions when coverage is expected.
        return


_maybe_start_coverage()
