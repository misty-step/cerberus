"""Tests for lib.github_platform."""

from __future__ import annotations

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
