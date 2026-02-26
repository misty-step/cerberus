"""Tests for scripts/validate-perspective.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "validate-perspective.py"
SPEC = importlib.util.spec_from_file_location("validate_perspective_py", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
reviewers:
  - name: trace
    perspective: correctness
  - name: guard
    perspective: security
"""
    )
    return config_path


def test_validate_perspective_accepts_known_value(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    is_valid, allowed = MODULE.validate_perspective(config_path, "security")

    assert is_valid is True
    assert allowed == ["correctness", "security"]


def test_validate_perspective_rejects_unknown_value(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    is_valid, allowed = MODULE.validate_perspective(config_path, "performance")

    assert is_valid is False
    assert allowed == ["correctness", "security"]


def test_main_reports_invalid_perspective(tmp_path: Path, capsys) -> None:
    config_path = _write_config(tmp_path)
    rc = MODULE.main(["--config", str(config_path), "--perspective", "performance"])

    assert rc == 1
    assert "Invalid perspective" in capsys.readouterr().err
