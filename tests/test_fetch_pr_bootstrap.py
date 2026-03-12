"""Tests for scripts/fetch-pr-bootstrap.py."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "fetch-pr-bootstrap.py"


def _import_script():
    spec = importlib.util.spec_from_file_location("fetch_pr_bootstrap", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_main_writes_diff_context_and_success_result(monkeypatch, tmp_path) -> None:
    mod = _import_script()
    diff_file = tmp_path / "review.diff"
    context_file = tmp_path / "pr-context.json"
    result_file = tmp_path / "result.json"

    monkeypatch.setattr(mod.platform, "fetch_pr_diff", lambda repo, pr: "diff --git a")
    monkeypatch.setattr(
        mod.platform,
        "fetch_pr_context",
        lambda repo, pr: {"title": "PR", "headRefName": "feature", "baseRefName": "master"},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fetch-pr-bootstrap.py",
            "--repo",
            "misty-step/cerberus",
            "--pr",
            "326",
            "--diff-file",
            str(diff_file),
            "--pr-context-file",
            str(context_file),
            "--result-file",
            str(result_file),
        ],
    )

    assert mod.main() == 0
    assert diff_file.read_text(encoding="utf-8") == "diff --git a"
    assert json.loads(context_file.read_text(encoding="utf-8"))["headRefName"] == "feature"
    assert json.loads(result_file.read_text(encoding="utf-8")) == {
        "ok": True,
        "error_kind": "",
        "error_message": "",
    }


def test_main_writes_auth_failure_result(monkeypatch, tmp_path, capsys) -> None:
    mod = _import_script()
    diff_file = tmp_path / "review.diff"
    context_file = tmp_path / "pr-context.json"
    result_file = tmp_path / "result.json"

    monkeypatch.setattr(mod.platform, "fetch_pr_diff", lambda repo, pr: "diff --git a")
    monkeypatch.setattr(
        mod.platform,
        "fetch_pr_context",
        lambda repo, pr: (_ for _ in ()).throw(mod.platform.GitHubAuthError("HTTP 401 Bad credentials")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "fetch-pr-bootstrap.py",
            "--repo",
            "misty-step/cerberus",
            "--pr",
            "326",
            "--diff-file",
            str(diff_file),
            "--pr-context-file",
            str(context_file),
            "--result-file",
            str(result_file),
        ],
    )

    assert mod.main() == 1
    assert json.loads(result_file.read_text(encoding="utf-8")) == {
        "ok": False,
        "error_kind": "auth",
        "error_message": "HTTP 401 Bad credentials",
    }
    assert "fetch-pr-bootstrap:" in capsys.readouterr().err
