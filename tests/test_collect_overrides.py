"""Tests for scripts/collect-overrides.py."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "collect-overrides.py"


def _import_script():
    spec = importlib.util.spec_from_file_location("collect_overrides", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_extract_override_comments_preserves_metacharacters() -> None:
    mod = _import_script()
    payload = "/council override sha=abc1234\nReason: `id` $(uname); rm -rf / | cat /etc/passwd"

    comments = [
        {"body": payload, "user": {"login": "attacker"}},
        {"body": "normal comment", "user": {"login": "ignored"}},
    ]
    extracted = mod.extract_override_comments(comments)

    assert extracted == [{"actor": "attacker", "body": payload}]


def test_collect_override_data_uses_repo_api(monkeypatch) -> None:
    mod = _import_script()
    payload = "/council override sha=abc1234\nReason: `id` $(uname); rm -rf / | cat /etc/passwd"
    calls: list[list[str]] = []

    def fake_gh_json(args, *, timeout=20):
        calls.append(args)
        endpoint = args[1]
        if "issues/77/comments" in endpoint and "page=1" in endpoint:
            return [{"body": payload, "user": {"login": "attacker"}}]
        if "collaborators/attacker/permission" in endpoint:
            return {"permission": "read"}
        return []

    monkeypatch.setattr(mod, "gh_json", fake_gh_json)

    overrides, permissions = mod.collect_override_data("owner/repo", 77)

    assert overrides == [{"actor": "attacker", "body": payload}]
    assert permissions == {"attacker": "read"}
    assert calls[0][0] == "api"
    assert "issues/77/comments" in calls[0][1]


def test_main_writes_safe_empty_outputs_when_fetch_fails(monkeypatch, tmp_path, capsys) -> None:
    mod = _import_script()
    output_file = tmp_path / "github_output.txt"

    def fail_collect(repo: str, pr_number: int):
        raise RuntimeError("boom")

    monkeypatch.setattr(mod, "collect_override_data", fail_collect)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "collect-overrides.py",
            "--repo",
            "owner/repo",
            "--pr",
            "77",
            "--github-output",
            str(output_file),
        ],
    )

    mod.main()

    text = output_file.read_text()
    assert "overrides<<" in text
    assert "actor_permissions<<" in text
    assert "[]" in text
    assert "{}" in text
    captured = capsys.readouterr()
    assert "Failed to fetch override comments" in captured.err


def test_stdout_mode_outputs_valid_json(monkeypatch, capsys) -> None:
    mod = _import_script()
    payload = "/council override sha=abc1234\nReason: done"

    def fake_collect(repo: str, pr_number: int):
        return ([{"actor": "author", "body": payload}], {"author": "write"})

    monkeypatch.setattr(mod, "collect_override_data", fake_collect)
    monkeypatch.setattr(
        sys,
        "argv",
        ["collect-overrides.py", "--repo", "owner/repo", "--pr", "2"],
    )

    mod.main()
    captured = capsys.readouterr()
    data = json.loads(captured.out)

    assert data["overrides"][0]["body"] == payload
    assert data["actor_permissions"] == {"author": "write"}
