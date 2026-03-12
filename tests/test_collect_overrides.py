"""Tests for scripts/collect-overrides.py."""
from __future__ import annotations

import importlib.util
import json
import subprocess
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
    payload = "/cerberus override sha=abc1234\nReason: `id` $(uname); rm -rf / | cat /etc/passwd"

    comments = [
        {"body": payload, "user": {"login": "attacker"}},
        {"body": "normal comment", "user": {"login": "ignored"}},
    ]
    extracted = mod.extract_override_comments(comments)

    assert extracted == [{"actor": "attacker", "body": payload}]


def test_collect_override_data_uses_repo_api(monkeypatch) -> None:
    mod = _import_script()
    payload = "/cerberus override sha=abc1234\nReason: `id` $(uname); rm -rf / | cat /etc/passwd"
    comment_calls: list[tuple[str, int]] = []
    permission_calls: list[list[str]] = []

    def fake_fetch_issue_comments(repo: str, pr_number: int, *, per_page: int = 100, max_pages: int = 20, stop_on_marker=None):
        comment_calls.append((repo, pr_number))
        return [{"body": payload, "user": {"login": "attacker"}}]

    def fake_gh_json(args, *, timeout=20):
        permission_calls.append(args)
        endpoint = args[1]
        if "collaborators/attacker/permission" in endpoint:
            return {"permission": "read"}
        return []

    monkeypatch.setattr(mod, "fetch_issue_comments", fake_fetch_issue_comments)
    monkeypatch.setattr(mod, "gh_json", fake_gh_json)

    overrides, permissions = mod.collect_override_data("owner/repo", 77)

    assert overrides == [{"actor": "attacker", "body": payload}]
    assert permissions == {"attacker": "read"}
    assert comment_calls == [("owner/repo", 77)]
    assert permission_calls[0][0] == "api"
    assert "collaborators/attacker/permission" in permission_calls[0][1]


def test_run_gh_raises_called_process_error_on_failure(monkeypatch) -> None:
    mod = _import_script()

    def fake_platform_run_gh(args, *, timeout=20):
        raise subprocess.CalledProcessError(returncode=9, cmd=args, output="out", stderr="err")

    monkeypatch.setattr(mod, "platform_run_gh", fake_platform_run_gh)

    try:
        mod.run_gh(["api", "repos/owner/repo/issues/1/comments"])
        raise AssertionError("expected CalledProcessError")
    except subprocess.CalledProcessError as exc:
        assert exc.returncode == 9
        assert exc.output == "out"
        assert exc.stderr == "err"


def test_gh_json_raises_value_error_for_invalid_json(monkeypatch) -> None:
    mod = _import_script()

    def fake_platform_gh_json(args, *, timeout=20, max_retries=3, base_delay=1.0):
        raise ValueError("invalid JSON from gh command ['api', 'repos/owner/repo/issues/1/comments']: nope")

    monkeypatch.setattr(mod, "platform_gh_json", fake_platform_gh_json)

    try:
        mod.gh_json(["api", "repos/owner/repo/issues/1/comments"])
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "invalid JSON from gh command" in str(exc)


def test_fetch_pr_comments_handles_multi_page_responses(monkeypatch) -> None:
    mod = _import_script()
    calls: list[tuple[str, int, int, int | None]] = []

    def fake_fetch_issue_comments(repo: str, pr_number: int, *, per_page: int = 100, max_pages: int = 20, stop_on_marker=None):
        calls.append((repo, pr_number, per_page, max_pages))
        assert per_page == 2
        return [{"id": 1}, {"id": 2}]

    monkeypatch.setattr(mod, "fetch_issue_comments", fake_fetch_issue_comments)

    comments = mod.fetch_pr_comments("owner/repo", 7, per_page=2)

    assert comments == [{"id": 1}, {"id": 2}]
    assert calls == [("owner/repo", 7, 2, None)]


def test_fetch_pr_comments_raises_on_non_list_payload(monkeypatch) -> None:
    mod = _import_script()

    def fake_fetch_issue_comments(repo: str, pr_number: int, *, per_page: int = 100, max_pages: int = 20, stop_on_marker=None):
        raise ValueError("unexpected comments payload type: dict")

    monkeypatch.setattr(mod, "fetch_issue_comments", fake_fetch_issue_comments)

    try:
        mod.fetch_pr_comments("owner/repo", 7)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "unexpected comments payload type" in str(exc)


def test_extract_override_comments_handles_malformed_entries() -> None:
    mod = _import_script()
    comments = [
        {"body": "/cerberus override sha=abc1234\nReason: no user"},
        {"body": "/cerberus override sha=abc1234\nReason: user none", "user": None},
        {"body": "/cerberus override sha=abc1234\nReason: user string", "user": "bad"},
        {"body": "/cerberus override sha=abc1234\nReason: login none", "user": {"login": None}},
        {"body": 123, "user": {"login": "ignored"}},
        {"body": "plain comment", "user": {"login": "ignored"}},
    ]

    extracted = mod.extract_override_comments(comments)

    assert extracted == [
        {"actor": "", "body": "/cerberus override sha=abc1234\nReason: no user"},
        {"actor": "", "body": "/cerberus override sha=abc1234\nReason: user none"},
        {"actor": "", "body": "/cerberus override sha=abc1234\nReason: user string"},
        {"actor": "", "body": "/cerberus override sha=abc1234\nReason: login none"},
    ]


def test_extract_override_comments_accepts_legacy_council_prefix() -> None:
    mod = _import_script()
    comments = [
        {"body": "/council override sha=abc1234\nReason: legacy command", "user": {"login": "dev"}},
        {"body": "/cerberus override sha=def5678\nReason: new command", "user": {"login": "dev"}},
        {"body": "plain comment", "user": {"login": "ignored"}},
    ]
    extracted = mod.extract_override_comments(comments)
    assert len(extracted) == 2
    assert extracted[0] == {"actor": "dev", "body": "/council override sha=abc1234\nReason: legacy command"}
    assert extracted[1] == {"actor": "dev", "body": "/cerberus override sha=def5678\nReason: new command"}


def test_fetch_actor_permissions_dedupes_and_handles_invalid_payloads(monkeypatch) -> None:
    mod = _import_script()
    calls: list[list[str]] = []

    def fake_gh_json(args, *, timeout=20):
        calls.append(args)
        endpoint = args[1]
        if "collaborators/alice/permission" in endpoint:
            return {"permission": "write"}
        if "collaborators/bob/permission" in endpoint:
            return {"permission": 123}
        if "collaborators/chris/permission" in endpoint:
            return ["not", "a", "dict"]
        raise AssertionError(f"unexpected endpoint: {endpoint}")

    monkeypatch.setattr(mod, "gh_json", fake_gh_json)

    permissions = mod.fetch_actor_permissions(
        "owner/repo",
        ["bob", "alice", "bob", "", "chris"],
    )

    assert permissions == {
        "alice": "write",
        "bob": "",
        "chris": "",
    }
    endpoints = [args[1] for args in calls]
    assert endpoints == [
        "repos/owner/repo/collaborators/alice/permission",
        "repos/owner/repo/collaborators/bob/permission",
        "repos/owner/repo/collaborators/chris/permission",
    ]


def test_fetch_actor_permissions_handles_expected_exceptions(monkeypatch) -> None:
    mod = _import_script()

    def fake_gh_json(args, *, timeout=20):
        endpoint = args[1]
        if "collaborators/alice/permission" in endpoint:
            raise mod.GitHubPermissionError("missing permission")
        if "collaborators/bob/permission" in endpoint:
            raise mod.TransientGitHubError("temporary")
        if "collaborators/chris/permission" in endpoint:
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=args,
                output="",
                stderr="boom",
            )
        if "collaborators/drew/permission" in endpoint:
            raise subprocess.TimeoutExpired(cmd=args, timeout=10)
        if "collaborators/erin/permission" in endpoint:
            raise ValueError("bad json")
        raise AssertionError(f"unexpected endpoint: {endpoint}")

    monkeypatch.setattr(mod, "gh_json", fake_gh_json)

    permissions = mod.fetch_actor_permissions("owner/repo", ["alice", "bob", "chris", "drew", "erin"])

    assert permissions == {"alice": "", "bob": "", "chris": "", "drew": "", "erin": ""}


def test_append_multiline_output_regenerates_delimiter_on_collision(monkeypatch, tmp_path) -> None:
    mod = _import_script()

    class FakeUUID:
        def __init__(self, hex_value: str):
            self.hex = hex_value

    values = iter(["dup", "safe"])

    def fake_uuid4():
        return FakeUUID(next(values))

    monkeypatch.setattr(mod, "uuid4", fake_uuid4)

    output = tmp_path / "github_output.txt"
    colliding_value = "payload with CERBERUS_OVERRIDES_dup inside"
    mod.append_multiline_output(output, "overrides", colliding_value)
    text = output.read_text()

    assert "overrides<<CERBERUS_OVERRIDES_safe" in text
    assert "overrides<<CERBERUS_OVERRIDES_dup" not in text


def test_main_writes_safe_empty_outputs_when_fetch_fails(monkeypatch, tmp_path, capsys) -> None:
    mod = _import_script()
    output_file = tmp_path / "github_output.txt"

    def fail_collect(repo: str, pr_number: int):
        raise mod.TransientGitHubError("boom")

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
    payload = "/cerberus override sha=abc1234\nReason: done"

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
