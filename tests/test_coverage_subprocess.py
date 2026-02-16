import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = (REPO_ROOT / "scripts" / "render-findings.py").resolve()


def test_subprocess_script_contributes_coverage(tmp_path: Path) -> None:
    """Smoke test: coverage must capture Python subprocesses (issue #195)."""
    config_file = os.environ.get("COVERAGE_PROCESS_START")
    if not config_file:
        pytest.skip("requires COVERAGE_PROCESS_START (run tests with coverage enabled)")
    coverage = pytest.importorskip("coverage")

    verdict_path = tmp_path / "verdict.json"
    out_path = tmp_path / "findings.md"
    verdict_path.write_text(json.dumps({"findings": []}), encoding="utf-8")

    env = os.environ.copy()
    cov_base = tmp_path / ".coverage"
    env["COVERAGE_FILE"] = str(cov_base)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--verdict-json",
            str(verdict_path),
            "--output",
            str(out_path),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr

    cov = coverage.Coverage(data_file=str(cov_base), config_file=config_file)
    cov.combine(data_paths=[str(tmp_path)], strict=True, keep=True)
    data = cov.get_data()

    measured = {str(Path(p).resolve()) for p in data.measured_files()}
    assert str(SCRIPT) in measured
