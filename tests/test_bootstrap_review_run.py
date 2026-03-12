"""Tests for scripts/bootstrap-review-run.py."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "bootstrap-review-run.py"


def _import_script():
    spec = importlib.util.spec_from_file_location("bootstrap_review_run", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_main_writes_review_run_contract(monkeypatch, tmp_path) -> None:
    mod = _import_script()
    diff_file = tmp_path / "review.diff"
    context_file = tmp_path / "pr-context.json"
    output = tmp_path / "review-run.json"

    diff_file.write_text("diff --git a/app.py b/app.py\n")
    context_file.write_text(
        '{"title": "PR", "headRefName": "feature/review-run", "baseRefName": "master"}'
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bootstrap-review-run.py",
            "--repo",
            "misty-step/cerberus",
            "--pr",
            "323",
            "--diff-file",
            str(diff_file),
            "--pr-context-file",
            str(context_file),
            "--output",
            str(output),
            "--token-env-var",
            "CERBERUS_TOKEN",
        ],
    )

    assert mod.main() == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["repository"] == "misty-step/cerberus"
    assert payload["pr_number"] == 323
    assert payload["diff_file"] == str(diff_file)
    assert payload["pr_context_file"] == str(context_file)
    assert payload["workspace_root"] == os.getcwd()
    assert payload["temp_dir"] == str(tmp_path)
    assert payload["head_ref"] == "feature/review-run"
    assert payload["base_ref"] == "master"
    assert payload["github"] == {
        "repo": "misty-step/cerberus",
        "pr_number": 323,
        "token_env_var": "CERBERUS_TOKEN",
    }


def test_main_returns_two_when_required_file_is_missing(monkeypatch, tmp_path, capsys) -> None:
    mod = _import_script()
    context_file = tmp_path / "pr-context.json"
    output = tmp_path / "review-run.json"

    context_file.write_text('{"title": "PR"}')
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bootstrap-review-run.py",
            "--repo",
            "misty-step/cerberus",
            "--pr",
            "323",
            "--diff-file",
            str(tmp_path / "missing.diff"),
            "--pr-context-file",
            str(context_file),
            "--output",
            str(output),
        ],
    )

    assert mod.main() == 2
    captured = capsys.readouterr()
    assert "bootstrap-review-run: diff file not found" in captured.err


def test_main_returns_two_when_pr_context_json_is_invalid(monkeypatch, tmp_path, capsys) -> None:
    mod = _import_script()
    diff_file = tmp_path / "review.diff"
    context_file = tmp_path / "pr-context.json"
    output = tmp_path / "review-run.json"

    diff_file.write_text("diff --git a/app.py b/app.py\n")
    context_file.write_text("{")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bootstrap-review-run.py",
            "--repo",
            "misty-step/cerberus",
            "--pr",
            "323",
            "--diff-file",
            str(diff_file),
            "--pr-context-file",
            str(context_file),
            "--output",
            str(output),
        ],
    )

    assert mod.main() == 2
    captured = capsys.readouterr()
    assert "bootstrap-review-run: invalid JSON in PR context file" in captured.err
