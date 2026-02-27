"""Tests for matrix/generate-matrix.py."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


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


def _write_wave_config(tmp_path: Path) -> Path:
    config = tmp_path / "wave-config.yml"
    config.write_text(
        "\n".join(
            [
                "waves:",
                "  definitions:",
                "    wave1:",
                "      reviewers: [TRACE]",
                "    wave2:",
                "      reviewers: [guard]",
                "reviewers:",
                "  - name: TRACE",
                "    perspective: correctness",
                "  - name: guard",
                "    perspective: security",
                "",
            ]
        )
    )
    return config


def _write_empty_wave_mapping_config(tmp_path: Path) -> Path:
    config = tmp_path / "empty-wave-config.yml"
    config.write_text(
        "\n".join(
            [
                "waves:",
                "  definitions:",
                "    wave1:",
                "      reviewers: [MISSING]",
                "reviewers:",
                "  - name: TRACE",
                "    perspective: correctness",
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


def test_generate_matrix_filters_by_wave_and_sets_model_wave(tmp_path: Path, monkeypatch) -> None:
    config = _write_wave_config(tmp_path)
    monkeypatch.setenv("REVIEW_WAVE", "wave2")
    monkeypatch.setenv("MODEL_TIER", "standard")
    mod.generate_matrix(str(config))
    payload = _load_matrix_output()
    assert len(payload["include"]) == 1
    entry = payload["include"][0]
    assert entry["reviewer"] == "guard"
    assert entry["model_wave"] == "wave2"
    assert entry["wave"] == "wave2"


def test_generate_matrix_fails_when_wave_filter_produces_empty_matrix(
    tmp_path: Path, monkeypatch
) -> None:
    config = _write_empty_wave_mapping_config(tmp_path)
    monkeypatch.setenv("REVIEW_WAVE", "wave1")
    with pytest.raises(SystemExit) as exc:
        mod.generate_matrix(str(config))
    assert exc.value.code == 1


def test_generate_matrix_fails_on_unknown_wave(tmp_path: Path, monkeypatch) -> None:
    config = _write_wave_config(tmp_path)
    monkeypatch.setenv("REVIEW_WAVE", "wave9")
    with pytest.raises(SystemExit) as exc:
        mod.generate_matrix(str(config))
    assert exc.value.code == 1
