"""Tests for lib.github_platform."""

from __future__ import annotations

import json
import subprocess

import pytest

from lib import github_platform as mod


def test_run_gh_raises_permission_error_for_403(monkeypatch) -> None:
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="HTTP 403: Resource not accessible by integration",
        )

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    with pytest.raises(mod.GitHubPermissionError, match="pull-requests: write"):
        mod.run_gh(["api", "repos/o/r/issues/1/comments"])


def test_run_gh_retries_transient_errors_then_succeeds(monkeypatch) -> None:
    calls = 0
    sleeps: list[float] = []

    def fake_run(args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout="",
                stderr="gh: HTTP 503: Service Unavailable",
            )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod.random, "uniform", lambda a, b: 0.0)
    monkeypatch.setattr(mod.time, "sleep", sleeps.append)

    result = mod.run_gh(["api", "repos/o/r/issues/1/comments"])

    assert result.stdout == "ok"
    assert calls == 2
    assert sleeps == [1.0]


def test_run_gh_exhausted_transient_errors_raise(monkeypatch) -> None:
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="gh: HTTP 503: Service Unavailable",
        )

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod.random, "uniform", lambda a, b: 0.0)
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: None)

    with pytest.raises(mod.TransientGitHubError, match="after 3 attempts"):
        mod.run_gh(["api", "repos/o/r/issues/1/comments"], max_retries=3)


def test_gh_json_raises_value_error_for_invalid_json(monkeypatch) -> None:
    def fake_run_gh(args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="{bad", stderr="")

    monkeypatch.setattr(mod, "run_gh", fake_run_gh)

    with pytest.raises(ValueError, match="invalid JSON from gh command"):
        mod.gh_json(["api", "repos/o/r/issues/1/comments"])


def test_fetch_issue_comments_paginates(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_gh_json(args, *, timeout=None, max_retries=3, base_delay=1.0):
        calls.append(args)
        endpoint = args[1]
        if "page=1" in endpoint:
            return [{"id": 1}, {"id": 2}]
        if "page=2" in endpoint:
            return [{"id": 3}]
        raise AssertionError(f"unexpected endpoint: {endpoint}")

    monkeypatch.setattr(mod, "gh_json", fake_gh_json)

    comments = mod.fetch_issue_comments("owner/repo", 42, per_page=2, max_pages=4)

    assert comments == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert calls == [
        ["api", "repos/owner/repo/issues/42/comments?per_page=2&page=1"],
        ["api", "repos/owner/repo/issues/42/comments?per_page=2&page=2"],
    ]


def test_fetch_issue_comments_stops_on_marker(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_gh_json(args, *, timeout=None, max_retries=3, base_delay=1.0):
        calls.append(args)
        endpoint = args[1]
        if "page=1" in endpoint:
            return [
                "skip-me",
                {"id": 1, "body": "plain"},
                {"id": 2, "body": "<!-- marker -->"},
                {"id": 3, "body": "after-marker"},
            ]
        raise AssertionError(f"unexpected endpoint: {endpoint}")

    monkeypatch.setattr(mod, "gh_json", fake_gh_json)

    comments = mod.fetch_issue_comments(
        "owner/repo",
        42,
        per_page=2,
        max_pages=4,
        stop_on_marker="<!-- marker -->",
    )

    assert comments == [{"id": 1, "body": "plain"}, {"id": 2, "body": "<!-- marker -->"}]
    assert calls == [["api", "repos/owner/repo/issues/42/comments?per_page=2&page=1"]]


def test_fetch_issue_comments_allows_unbounded_pagination(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_gh_json(args, *, timeout=None, max_retries=3, base_delay=1.0):
        calls.append(args)
        endpoint = args[1]
        if endpoint.endswith("page=1"):
            return [{"id": index} for index in range(100)]
        if endpoint.endswith("page=2"):
            return []
        raise AssertionError(f"unexpected endpoint: {endpoint}")

    monkeypatch.setattr(mod, "gh_json", fake_gh_json)

    comments = mod.fetch_issue_comments("owner/repo", 42, max_pages=None)

    assert comments == [{"id": index} for index in range(100)]
    assert calls == [
        ["api", "repos/owner/repo/issues/42/comments?per_page=100&page=1"],
        ["api", "repos/owner/repo/issues/42/comments?per_page=100&page=2"],
    ]


def test_create_issue_comment_uses_shared_transport(monkeypatch, tmp_path) -> None:
    body_file = tmp_path / "body.md"
    body_file.write_text("body")
    seen: list[list[str]] = []

    def fake_run_gh(args, **kwargs):
        seen.append(args)
        assert kwargs["timeout"] == mod.DEFAULT_GH_TIMEOUT
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mod, "run_gh", fake_run_gh)

    mod.create_issue_comment(repo="owner/repo", number=7, body_file=str(body_file))

    assert seen == [["api", "repos/owner/repo/issues/7/comments", "-F", f"body=@{body_file}"]]
    assert mod.DEFAULT_GH_TIMEOUT == 20


def test_update_issue_comment_uses_shared_transport(monkeypatch, tmp_path) -> None:
    body_file = tmp_path / "body.md"
    body_file.write_text("body")
    seen: list[list[str]] = []

    def fake_run_gh(args, **kwargs):
        seen.append(args)
        assert kwargs["timeout"] == mod.DEFAULT_GH_TIMEOUT
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mod, "run_gh", fake_run_gh)

    mod.update_issue_comment(repo="owner/repo", comment_id=11, body_file=str(body_file))

    assert seen == [
        ["api", "repos/owner/repo/issues/comments/11", "-X", "PATCH", "-F", f"body=@{body_file}"]
    ]


def test_list_pr_reviews_uses_adapter_json(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_gh_json(args, *, timeout=None, max_retries=3, base_delay=1.0):
        calls.append(args)
        assert timeout == mod.DEFAULT_GH_TIMEOUT
        return [[{"id": 9, "body": "ok"}], [{"id": 10, "body": "again"}]]

    monkeypatch.setattr(mod, "gh_json", fake_gh_json)

    reviews = mod.list_pr_reviews("owner/repo", 42)

    assert reviews == [{"id": 9, "body": "ok"}, {"id": 10, "body": "again"}]
    assert calls == [[
        "api",
        "--paginate",
        "--slurp",
        "repos/owner/repo/pulls/42/reviews?per_page=100",
    ]]


def test_list_pr_files_flattens_paginated_pages(monkeypatch) -> None:
    def fake_gh_json(args, *, timeout=None, max_retries=3, base_delay=1.0):
        assert args == [
            "api",
            "--paginate",
            "--slurp",
            "repos/owner/repo/pulls/5/files?per_page=100",
        ]
        assert timeout == mod.DEFAULT_GH_TIMEOUT
        return [
            [{"filename": "a.py", "patch": "@@ -1 +1 @@\n+hi"}],
            [{"filename": "b.py"}],
        ]

    monkeypatch.setattr(mod, "gh_json", fake_gh_json)

    files = mod.list_pr_files("owner/repo", 5)

    assert [f.get("filename") for f in files] == ["a.py", "b.py"]


def test_create_pr_review_posts_json_payload(monkeypatch) -> None:
    seen_payload: dict | None = None
    payload_path: str | None = None

    def fake_run_gh(args, **kwargs):
        nonlocal seen_payload, payload_path
        assert args[0:4] == ["api", "-X", "POST", "repos/owner/repo/pulls/7/reviews"]
        assert kwargs["timeout"] == mod.DEFAULT_GH_TIMEOUT
        payload_path = args[args.index("--input") + 1]
        with open(payload_path, encoding="utf-8") as handle:
            seen_payload = json.load(handle)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout='{"id": 123}', stderr="")

    monkeypatch.setattr(mod, "run_gh", fake_run_gh)

    out = mod.create_pr_review(
        repo="owner/repo",
        pr_number=7,
        commit_id="deadbeef",
        body="hello",
        comments=[{"path": "a.py", "position": 3, "body": "c"}],
    )

    assert out == {"id": 123}
    assert seen_payload == {
        "event": "COMMENT",
        "commit_id": "deadbeef",
        "body": "hello",
        "comments": [{"path": "a.py", "position": 3, "body": "c"}],
    }
    assert payload_path is not None
    assert not mod.os.path.exists(payload_path)


def test_create_pr_review_cleans_up_temp_file_on_error(monkeypatch) -> None:
    payload_path: str | None = None

    def fake_run_gh(args, **kwargs):
        nonlocal payload_path
        payload_path = args[args.index("--input") + 1]
        raise mod.TransientGitHubError("boom")

    monkeypatch.setattr(mod, "run_gh", fake_run_gh)

    with pytest.raises(mod.TransientGitHubError, match="boom"):
        mod.create_pr_review(
            repo="owner/repo",
            pr_number=7,
            commit_id="deadbeef",
            body="hello",
            comments=[],
        )

    assert payload_path is not None
    assert not mod.os.path.exists(payload_path)
