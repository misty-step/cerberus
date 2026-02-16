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


_CERBERUS_COVERAGE_STARTED = False

if os.environ.get("COVERAGE_PROCESS_START"):
    try:
        import coverage
    except ImportError:
        pass
    else:
        try:
            coverage.process_startup()
        except Exception:  # noqa: BLE001
            # Never break the subprocess if coverage is misconfigured.
            # Our smoke test should catch regressions when coverage is expected.
            pass
        else:
            _CERBERUS_COVERAGE_STARTED = True
