"""Tests for matrix/filter-panel.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "matrix"))

# Import after path insertion
import importlib

filter_panel = importlib.import_module("filter-panel")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FULL_MATRIX = {
    "include": [
        {"reviewer": "trace", "perspective": "correctness"},
        {"reviewer": "atlas", "perspective": "architecture"},
        {"reviewer": "guard", "perspective": "security"},
        {"reviewer": "flux", "perspective": "performance"},
        {"reviewer": "craft", "perspective": "maintainability"},
    ]
}


@pytest.fixture(autouse=True)
def _tmp_files(tmp_path, monkeypatch):
    """Redirect /tmp file I/O to a temp directory."""
    matrix_file = tmp_path / "matrix-output.json"
    count_file = tmp_path / "matrix-count.txt"
    names_file = tmp_path / "matrix-names.txt"

    matrix_file.write_text(json.dumps(FULL_MATRIX))

    # Patch open calls inside filter-panel to use tmp_path
    original_open = open

    def patched_open(path, *args, **kwargs):
        path_str = str(path)
        if path_str == "/tmp/matrix-output.json":
            return original_open(str(matrix_file), *args, **kwargs)
        if path_str == "/tmp/matrix-count.txt":
            return original_open(str(count_file), *args, **kwargs)
        if path_str == "/tmp/matrix-names.txt":
            return original_open(str(names_file), *args, **kwargs)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", patched_open)

    return tmp_path, matrix_file, count_file, names_file


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFilterPanel:
    """Tests for the panel filter script."""

    def test_filters_to_matching_perspectives(self, _tmp_files):
        tmp_path, matrix_file, count_file, names_file = _tmp_files
        panel = ["correctness", "security", "maintainability"]

        with mock.patch("sys.argv", ["filter-panel.py", json.dumps(panel)]):
            filter_panel.main()

        result = json.loads(matrix_file.read_text())
        perspectives = [r["perspective"] for r in result["include"]]
        assert perspectives == ["correctness", "security", "maintainability"]
        assert count_file.read_text() == "3"
        assert names_file.read_text() == "trace,guard,craft"

    def test_falls_back_to_full_matrix_when_no_match(self, _tmp_files, capsys):
        tmp_path, matrix_file, count_file, names_file = _tmp_files
        panel = ["nonexistent"]

        with mock.patch("sys.argv", ["filter-panel.py", json.dumps(panel)]):
            filter_panel.main()

        result = json.loads(matrix_file.read_text())
        assert len(result["include"]) == 5  # Full matrix preserved
        assert count_file.read_text() == "5"
        captured = capsys.readouterr()
        assert "warning" in captured.err.lower() or "full matrix" in captured.err.lower()

    def test_single_reviewer_panel(self, _tmp_files):
        tmp_path, matrix_file, count_file, names_file = _tmp_files
        panel = ["architecture"]

        with mock.patch("sys.argv", ["filter-panel.py", json.dumps(panel)]):
            filter_panel.main()

        result = json.loads(matrix_file.read_text())
        assert len(result["include"]) == 1
        assert result["include"][0]["reviewer"] == "atlas"
        assert count_file.read_text() == "1"
        assert names_file.read_text() == "atlas"

    def test_preserves_all_entry_fields(self, _tmp_files):
        tmp_path, matrix_file, count_file, names_file = _tmp_files
        panel = ["trace"]

        with mock.patch("sys.argv", ["filter-panel.py", json.dumps(panel)]):
            filter_panel.main()

        result = json.loads(matrix_file.read_text())
        entry = result["include"][0]
        assert entry["reviewer"] == "trace"
        assert entry["perspective"] == "correctness"

    def test_empty_panel_triggers_fallback(self, _tmp_files, capsys):
        tmp_path, matrix_file, count_file, names_file = _tmp_files
        panel = []

        with mock.patch("sys.argv", ["filter-panel.py", json.dumps(panel)]):
            filter_panel.main()

        result = json.loads(matrix_file.read_text())
        assert len(result["include"]) == 5  # Full fallback
