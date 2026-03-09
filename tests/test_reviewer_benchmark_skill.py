"""Regression tests for the reviewer benchmark skill collector."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / ".agents" / "skills" / "reviewer-benchmark" / "scripts" / "collect_pr_reviews.py"


def _import_script():
    spec = importlib.util.spec_from_file_location("reviewer_benchmark_collect", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_run_json_ignores_stderr_when_stdout_is_valid_json(monkeypatch) -> None:
    mod = _import_script()

    def fake_run(cmd, *, text, capture_output, check):
        assert text is True
        assert capture_output is True
        assert check is True
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok": true}', stderr="warning")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    assert mod.run_json(["gh", "repo", "list"]) == {"ok": True}


def test_run_json_raises_clear_error_for_invalid_json(monkeypatch) -> None:
    mod = _import_script()

    def fake_run(cmd, *, text, capture_output, check):
        return subprocess.CompletedProcess(cmd, 0, stdout="not-json", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    try:
        mod.run_json(["gh", "repo", "list", "misty-step"])
        raise AssertionError("expected GhCommandError")
    except mod.GhCommandError as exc:
        assert "non-JSON output" in str(exc)
        assert "gh repo list misty-step" in str(exc)


def test_list_repos_uses_repo_limit_and_filters_archived(monkeypatch) -> None:
    mod = _import_script()
    calls: list[list[str]] = []

    def fake_run_json(cmd):
        calls.append(cmd)
        return [
            {"nameWithOwner": "misty-step/cerberus", "isArchived": False},
            {"nameWithOwner": "misty-step/old", "isArchived": True},
        ]

    monkeypatch.setattr(mod, "run_json", fake_run_json)

    repos = mod.list_repos("misty-step", [], 250)

    assert repos == ["misty-step/cerberus"]
    assert "--limit" in calls[0]
    assert "250" in calls[0]


def test_list_repos_dedupes_explicit_repos() -> None:
    mod = _import_script()

    repos = mod.list_repos(
        "misty-step",
        ["misty-step/cerberus", "misty-step/cerberus", "misty-step/volume"],
        250,
    )

    assert repos == ["misty-step/cerberus", "misty-step/volume"]


def test_main_returns_error_when_repo_listing_fails(monkeypatch, tmp_path, capsys) -> None:
    mod = _import_script()
    out = tmp_path / "out.json"

    def boom(org, explicit_repos, repo_limit):
        raise mod.GhCommandError("token expired")

    monkeypatch.setattr(mod, "list_repos", boom)

    code = mod.main(["--org", "misty-step", "--since", "2026-03-01", "--out", str(out)])

    assert code == 1
    captured = capsys.readouterr()
    assert "Failed to list repos for org 'misty-step': token expired" in captured.err
    assert not out.exists()


def test_main_records_repo_errors_without_aborting(monkeypatch, tmp_path, capsys) -> None:
    mod = _import_script()
    out = tmp_path / "out.json"

    monkeypatch.setattr(mod, "list_repos", lambda org, explicit_repos, repo_limit: ["a/repo", "b/repo"])

    def fake_collect_repo(repo, since, limit):
        if repo == "a/repo":
            raise mod.GhCommandError("auth warning")
        return [{"number": 1}]

    monkeypatch.setattr(mod, "collect_repo", fake_collect_repo)

    code = mod.main(
        [
            "--org",
            "misty-step",
            "--since",
            "2026-03-01",
            "--out",
            str(out),
            "--limit",
            "5",
        ]
    )

    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload == {
        "org": "misty-step",
        "since": "2026-03-01",
        "repo_limit": 1000,
        "pull_request_limit": 5,
        "repo_listing_truncated": False,
        "repos": {
            "a/repo": {"pull_requests": [], "error": "auth warning", "truncated": False},
            "b/repo": {"pull_requests": [{"number": 1}], "error": None, "truncated": False},
        },
    }
    assert "2/2 repos collected" in capsys.readouterr().err


def test_build_repo_result_is_consistent() -> None:
    mod = _import_script()

    assert mod.build_repo_result(pull_requests=[{"number": 1}]) == {
        "pull_requests": [{"number": 1}],
        "error": None,
        "truncated": False,
    }
    assert mod.build_repo_result(error="boom") == {
        "pull_requests": [],
        "error": "boom",
        "truncated": False,
    }


def test_validate_since_rejects_non_dates() -> None:
    mod = _import_script()

    assert mod.validate_since("2026-03-01") == "2026-03-01"
    try:
        mod.validate_since("2026-03-01 label:security")
        raise AssertionError("expected ArgumentTypeError")
    except mod.argparse.ArgumentTypeError as exc:
        assert "YYYY-MM-DD" in str(exc)


def test_main_reports_output_write_failures(monkeypatch, tmp_path, capsys) -> None:
    mod = _import_script()
    out = tmp_path / "out.json"

    monkeypatch.setattr(mod, "list_repos", lambda org, explicit_repos, repo_limit: ["a/repo"])
    monkeypatch.setattr(mod, "collect_repo", lambda repo, since, limit: [{"number": 1}])

    def fail_open(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(mod, "open", fail_open, raising=False)

    code = mod.main(["--org", "misty-step", "--since", "2026-03-01", "--out", str(out)])

    assert code == 1
    assert "Failed to write output file" in capsys.readouterr().err


def test_main_persists_truncation_metadata(monkeypatch, tmp_path) -> None:
    mod = _import_script()
    out = tmp_path / "out.json"

    monkeypatch.setattr(mod, "list_repos", lambda org, explicit_repos, repo_limit: ["a/repo", "b/repo"])
    monkeypatch.setattr(
        mod,
        "collect_repo",
        lambda repo, since, limit: [{"number": 1}] if repo == "a/repo" else [{"number": 2}, {"number": 3}],
    )

    code = mod.main(
        [
            "--org",
            "misty-step",
            "--since",
            "2026-03-01",
            "--out",
            str(out),
            "--limit",
            "1",
            "--repo-limit",
            "2",
        ]
    )

    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["repo_listing_truncated"] is True
    assert payload["repos"]["a/repo"]["truncated"] is True
