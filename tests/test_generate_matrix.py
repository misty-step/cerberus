"""Tests for matrix/generate-matrix.py."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "matrix" / "generate-matrix.py"

spec = importlib.util.spec_from_file_location("generate_matrix_script", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def _write_config(tmp_path: Path) -> Path:
    config = tmp_path / "config.yml"
    config.write_text(
        "\n".join(
            [
                "reviewers:",
                "  - name: TRACE",
                "    perspective: correctness",
                "    description: Correctness - Find the bug",
                "  - name: guard",
                "    perspective: security",
                "",
            ]
        )
    )
    return config


def _load_matrix_output() -> dict:
    return json.loads(Path("/tmp/matrix-output.json").read_text())


def test_generate_matrix_includes_model_tier_when_env_set(tmp_path: Path, monkeypatch) -> None:
    config = _write_config(tmp_path)
    monkeypatch.setenv("MODEL_TIER", "  FLASH  ")
    mod.generate_matrix(str(config))
    payload = _load_matrix_output()
    assert payload["include"][0]["model_tier"] == "flash"
    assert payload["include"][1]["model_tier"] == "flash"


def test_generate_matrix_omits_model_tier_when_env_unset(tmp_path: Path, monkeypatch) -> None:
    config = _write_config(tmp_path)
    monkeypatch.delenv("MODEL_TIER", raising=False)
    mod.generate_matrix(str(config))
    payload = _load_matrix_output()
    assert "model_tier" not in payload["include"][0]
    assert "model_tier" not in payload["include"][1]
