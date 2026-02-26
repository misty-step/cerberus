"""Tests for scripts/read-reviewer-profile.py CLI."""

import importlib
import json
import subprocess
import sys
from pathlib import Path

_script_path = Path(__file__).parent.parent / "scripts" / "read-reviewer-profile.py"
_spec = importlib.util.spec_from_file_location("read_reviewer_profile_cli", _script_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
main = _mod.main


def _write_config(tmp_path: Path, content: str) -> str:
    p = tmp_path / "reviewer-profiles.yml"
    p.write_text(content)
    return str(p)


def _minimal_config() -> str:
    return """
version: 1
base:
  provider: openrouter
perspectives:
  security:
    model: minimax/minimax-m2.5
"""


def test_profile_json_success(tmp_path: Path, capsys) -> None:
    cfg = _write_config(tmp_path, _minimal_config())

    code = main(["profile-json", "--config", cfg, "--perspective", "security"])

    assert code == 0
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["provider"] == "openrouter"
    assert payload["model"] == "minimax/minimax-m2.5"


def test_config_error_returns_exit_2(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "profile-json",
            "--config",
            str(tmp_path / "missing.yml"),
            "--perspective",
            "security",
        ]
    )

    assert code == 2
    assert "reviewer profiles error" in capsys.readouterr().err


def test_blank_perspective_is_rejected(tmp_path: Path, capsys) -> None:
    cfg = _write_config(tmp_path, _minimal_config())

    code = main(["profile-json", "--config", cfg, "--perspective", "   "])

    assert code == 2
    assert "--perspective must be non-empty" in capsys.readouterr().err


def test_unknown_command_branch(monkeypatch, tmp_path: Path, capsys) -> None:
    cfg = _write_config(tmp_path, _minimal_config())

    class Args:
        cmd = "unknown"
        config = cfg
        perspective = "security"

    monkeypatch.setattr(_mod.argparse.ArgumentParser, "parse_args", lambda self, argv: Args())

    code = main([])

    assert code == 2
    assert "unknown command" in capsys.readouterr().err


def test_script_entrypoint_works_via_subprocess(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, _minimal_config())

    result = subprocess.run(
        [
            sys.executable,
            str(_script_path),
            "profile-json",
            "--config",
            cfg,
            "--perspective",
            "security",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["model"] == "minimax/minimax-m2.5"
