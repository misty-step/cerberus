"""Tests for lib.github PR comment upsert."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from lib.github import (
    CommentPermissionError,
    find_comment_by_marker,
    upsert_pr_comment,
)
from lib.github_platform import fetch_issue_comments


class TestFindCommentByMarker:
    def test_finds_matching_comment(self):
        comments = [
            {"id": 100, "body": "unrelated comment"},
            {"id": 200, "body": "<!-- cerberus:council -->\nCerberus verdict"},
            {"id": 300, "body": "another comment"},
        ]
        assert find_comment_by_marker(comments, "<!-- cerberus:council -->") == 200

    def test_returns_none_when_no_match(self):
        comments = [
            {"id": 100, "body": "unrelated"},
            {"id": 200, "body": "also unrelated"},
        ]
        assert find_comment_by_marker(comments, "<!-- cerberus:council -->") is None

    def test_returns_none_for_empty_list(self):
        assert find_comment_by_marker([], "<!-- cerberus:council -->") is None

    def test_different_markers_dont_conflict(self):
        comments = [
            {"id": 100, "body": "<!-- cerberus:correctness -->\nReview"},
            {"id": 200, "body": "<!-- cerberus:council -->\nCerberus verdict"},
        ]
        assert find_comment_by_marker(comments, "<!-- cerberus:correctness -->") == 100
        assert find_comment_by_marker(comments, "<!-- cerberus:council -->") == 200
        assert find_comment_by_marker(comments, "<!-- cerberus:security -->") is None

    def test_skips_non_integer_ids(self):
        comments = [
            {"id": "IC_abc123", "body": "<!-- cerberus:council -->\nContent"},
        ]
        assert find_comment_by_marker(comments, "<!-- cerberus:council -->") is None

    def test_first_match_wins(self):
        comments = [
            {"id": 100, "body": "<!-- cerberus:council -->\nFirst"},
            {"id": 200, "body": "<!-- cerberus:council -->\nSecond"},
        ]
        assert find_comment_by_marker(comments, "<!-- cerberus:council -->") == 100


class TestFindCommentUrlByMarker:
    def test_returns_url_for_matching_comment(self):
        from lib.github import find_comment_url_by_marker

        comments = [
            {"id": 1, "body": "nope", "html_url": "https://x/1"},
            {"id": 2, "body": "<!-- cerberus:council -->\nVerdict", "html_url": "https://x/2"},
        ]
        assert find_comment_url_by_marker(comments, "<!-- cerberus:council -->") == "https://x/2"

    def test_returns_none_when_url_missing(self):
        from lib.github import find_comment_url_by_marker

        comments = [
            {"id": 2, "body": "<!-- cerberus:council -->\nVerdict", "html_url": ""},
        ]
        assert find_comment_url_by_marker(comments, "<!-- cerberus:council -->") is None


class TestUpsertPrComment:
    def test_creates_comment_when_none_exists(self, monkeypatch, tmp_path):
        body_file = tmp_path / "body.md"
        body_file.write_text("Test body")

        calls: list[tuple[str, int, str]] = []

        def fake_create_issue_comment(*, repo: str, number: int, body_file: str):
            calls.append((repo, number, body_file))
            return subprocess.CompletedProcess(args=["gh"], returncode=0, stdout="", stderr="")

        import lib.github as mod

        monkeypatch.setattr(mod, "create_issue_comment", fake_create_issue_comment)

        upsert_pr_comment(
            repo="owner/repo",
            pr_number=42,
            marker="<!-- test -->",
            body_file=str(body_file),
            comments=[],
        )

        assert calls == [("owner/repo", 42, str(body_file))]

    def test_updates_existing_comment(self, monkeypatch, tmp_path):
        body_file = tmp_path / "body.md"
        body_file.write_text("Updated body")

        calls: list[tuple[str, int, str]] = []

        def fake_update_issue_comment(*, repo: str, comment_id: int, body_file: str):
            calls.append((repo, comment_id, body_file))
            return subprocess.CompletedProcess(args=["gh"], returncode=0, stdout="", stderr="")

        import lib.github as mod

        monkeypatch.setattr(mod, "update_issue_comment", fake_update_issue_comment)

        comments = [
            {"id": 555, "body": "<!-- test -->\nOld body"},
        ]

        upsert_pr_comment(
            repo="owner/repo",
            pr_number=42,
            marker="<!-- test -->",
            body_file=str(body_file),
            comments=comments,
        )

        assert calls == [("owner/repo", 555, str(body_file))]

    def test_fetches_comments_when_not_provided(self, monkeypatch, tmp_path):
        body_file = tmp_path / "body.md"
        body_file.write_text("Body")

        fetch_calls: list[tuple[str, int, int, int, str | None]] = []
        update_calls: list[tuple[str, int, str]] = []

        def fake_fetch_issue_comments(
            repo: str,
            number: int,
            *,
            per_page: int = 100,
            max_pages: int = 20,
            stop_on_marker: str | None = None,
        ):
            fetch_calls.append((repo, number, per_page, max_pages, stop_on_marker))
            return [{"id": 999, "body": "<!-- test -->\nContent"}]

        def fake_update_issue_comment(*, repo: str, comment_id: int, body_file: str):
            update_calls.append((repo, comment_id, body_file))
            return subprocess.CompletedProcess(args=["gh"], returncode=0, stdout="", stderr="")

        import lib.github as mod

        monkeypatch.setattr(mod, "fetch_issue_comments", fake_fetch_issue_comments)
        monkeypatch.setattr(mod, "update_issue_comment", fake_update_issue_comment)

        upsert_pr_comment(
            repo="owner/repo",
            pr_number=42,
            marker="<!-- test -->",
            body_file=str(body_file),
        )

        assert fetch_calls == [("owner/repo", 42, 100, 20, None)]
        assert update_calls == [("owner/repo", 999, str(body_file))]


def test_fetch_issue_comments_uses_shared_transport(monkeypatch) -> None:
    import lib.github_platform as platform

    calls = []

    def mock_gh_json(args, *, timeout=None, max_retries=3, base_delay=1.0):
        calls.append(args)
        return [{"id": 1, "body": "x"}]

    monkeypatch.setattr(platform, "gh_json", mock_gh_json)
    comments = fetch_issue_comments("owner/repo", 42, per_page=100, max_pages=1)
    assert comments == [{"id": 1, "body": "x"}]
    assert calls == [["api", "repos/owner/repo/issues/42/comments?per_page=100&page=1"]]


def test_github_helper_runs_as_standalone_script() -> None:
    script = Path(__file__).resolve().parent.parent / "scripts" / "lib" / "github.py"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        env=env,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "usage:" in result.stdout.lower()

def test_fetch_comments_paginates(monkeypatch):
    import lib.github as mod

    seen: list[tuple[str, int, int, int, str | None]] = []

    def fake_fetch_issue_comments(repo: str, number: int, *, per_page=100, max_pages=20, stop_on_marker=None):
        seen.append((repo, number, per_page, max_pages, stop_on_marker))
        return [{"id": 1, "body": "a"}, {"id": 2, "body": "b"}, {"id": 3, "body": "c"}]

    monkeypatch.setattr(mod, "fetch_issue_comments", fake_fetch_issue_comments)

    comments = mod.fetch_comments("o/r", 5, per_page=2, max_pages=20)
    assert [c.get("id") for c in comments] == [1, 2, 3]
    assert seen == [("o/r", 5, 2, 20, None)]

def test_fetch_comments_stop_on_marker_exits_early(monkeypatch):
    import lib.github as mod

    seen: list[tuple[str, int, int, int, str | None]] = []

    def fake_fetch_issue_comments(repo: str, number: int, *, per_page=100, max_pages=20, stop_on_marker=None):
        seen.append((repo, number, per_page, max_pages, stop_on_marker))
        return [
            {"id": 1, "body": "first comment"},
            {"id": 2, "body": "<!-- cerberus:council -->\nCerberus verdict"},
        ]

    monkeypatch.setattr(mod, "fetch_issue_comments", fake_fetch_issue_comments)

    comments = mod.fetch_comments("o/r", 5, per_page=2, max_pages=20, stop_on_marker="<!-- cerberus:council -->")
    assert [c.get("id") for c in comments] == [1, 2]
    assert seen == [("o/r", 5, 2, 20, "<!-- cerberus:council -->")]

def test_fetch_comments_stop_on_marker_not_found_fetches_all(monkeypatch):
    import lib.github as mod

    seen: list[tuple[str, int, int, int, str | None]] = []

    def fake_fetch_issue_comments(repo: str, number: int, *, per_page=100, max_pages=20, stop_on_marker=None):
        seen.append((repo, number, per_page, max_pages, stop_on_marker))
        return [
            {"id": 1, "body": "first comment"},
            {"id": 2, "body": "second comment"},
            {"id": 3, "body": "third comment"},
        ]

    monkeypatch.setattr(mod, "fetch_issue_comments", fake_fetch_issue_comments)

    comments = mod.fetch_comments("o/r", 5, per_page=2, max_pages=20, stop_on_marker="<!-- not-found -->")
    assert [c.get("id") for c in comments] == [1, 2, 3]
    assert seen == [("o/r", 5, 2, 20, "<!-- not-found -->")]

def test_fetch_comments_without_stop_on_marker_fetches_all(monkeypatch):
    import lib.github as mod

    seen: list[tuple[str, int, int, int, str | None]] = []

    def fake_fetch_issue_comments(repo: str, number: int, *, per_page=100, max_pages=20, stop_on_marker=None):
        seen.append((repo, number, per_page, max_pages, stop_on_marker))
        return [
            {"id": 1, "body": "<!-- cerberus:council -->"},
            {"id": 2, "body": "second"},
            {"id": 3, "body": "third"},
        ]

    monkeypatch.setattr(mod, "fetch_issue_comments", fake_fetch_issue_comments)

    comments = mod.fetch_comments("o/r", 5, per_page=2, max_pages=20)
    assert [c.get("id") for c in comments] == [1, 2, 3]
    assert seen == [("o/r", 5, 2, 20, None)]


def test_fetch_comments_translates_permission_errors(monkeypatch):
    import lib.github as mod

    def fake_fetch(*args, **kwargs):
        raise mod.PlatformPermissionError("no permission")

    monkeypatch.setattr(mod, "fetch_issue_comments", fake_fetch)

    with pytest.raises(mod.CommentPermissionError, match="no permission"):
        mod.fetch_comments("o/r", 5)


def test_fetch_comments_translates_transient_errors(monkeypatch):
    import lib.github as mod

    def fake_fetch(*args, **kwargs):
        raise mod.PlatformTransientGitHubError("temporary")

    monkeypatch.setattr(mod, "fetch_issue_comments", fake_fetch)

    with pytest.raises(mod.TransientGitHubError, match="temporary"):
        mod.fetch_comments("o/r", 5)


def test_fetch_comments_returns_empty_list_on_invalid_json_payload(monkeypatch):
    import lib.github as mod

    def fake_fetch(*args, **kwargs):
        raise ValueError("bad payload")

    monkeypatch.setattr(mod, "fetch_issue_comments", fake_fetch)

    assert mod.fetch_comments("o/r", 5) == []

def test_multiple_markers_dont_conflict(monkeypatch, tmp_path):
    body_file = tmp_path / "body.md"
    body_file.write_text("Body for council")

    calls: list[tuple[str, int, str]] = []

    def fake_update_issue_comment(*, repo: str, comment_id: int, body_file: str):
        calls.append((repo, comment_id, body_file))
        return subprocess.CompletedProcess(args=["gh"], returncode=0, stdout="", stderr="")

    import lib.github as mod

    monkeypatch.setattr(mod, "update_issue_comment", fake_update_issue_comment)

    comments = [
        {"id": 100, "body": "<!-- cerberus:correctness -->\nReview"},
        {"id": 200, "body": "<!-- cerberus:council -->\nVerdict"},
    ]

    upsert_pr_comment(
        repo="owner/repo",
        pr_number=42,
        marker="<!-- cerberus:council -->",
        body_file=str(body_file),
        comments=comments,
    )

    assert calls == [("owner/repo", 200, str(body_file))]

def test_permission_denied_raises(monkeypatch, tmp_path):
    body_file = tmp_path / "body.md"
    body_file.write_text("Body")

    def mock_create_issue_comment(*, repo: str, number: int, body_file: str):
        import lib.github_platform as platform

        raise platform.GitHubPermissionError("no permission")

    import lib.github as mod

    monkeypatch.setattr(mod, "create_issue_comment", mock_create_issue_comment)

    with pytest.raises(CommentPermissionError):
        upsert_pr_comment(
            repo="owner/repo",
            pr_number=42,
            marker="<!-- test -->",
            body_file=str(body_file),
            comments=[],
        )


def test_fetch_comments_translates_platform_transient_error(monkeypatch):
    import lib.github as mod
    import lib.github_platform as platform

    def fake_fetch_issue_comments(*args, **kwargs):
        raise platform.TransientGitHubError("temporary")

    monkeypatch.setattr(mod, "fetch_issue_comments", fake_fetch_issue_comments)

    with pytest.raises(mod.TransientGitHubError, match="temporary"):
        mod.fetch_comments("o/r", 5)


def test_fetch_comments_returns_empty_list_on_invalid_payload(monkeypatch):
    import lib.github as mod

    def fake_fetch_issue_comments(*args, **kwargs):
        raise ValueError("bad payload")

    monkeypatch.setattr(mod, "fetch_issue_comments", fake_fetch_issue_comments)

    assert mod.fetch_comments("o/r", 5) == []


class TestRunGhErrorHandling:
    def test_403_raises_permission_error(self, monkeypatch):
        def mock_subprocess_run(args, **kwargs):
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout="",
                stderr="HTTP 403: Resource not accessible by integration",
            )

        import lib.github as mod

        monkeypatch.setattr(mod.subprocess, "run", mock_subprocess_run)

        with pytest.raises(CommentPermissionError, match="pull-requests: write"):
            mod._run_gh(["api", "repos/x/y/issues/1/comments"])

    def test_insufficient_permission_raises(self, monkeypatch):
        def mock_subprocess_run(args, **kwargs):
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout="",
                stderr="insufficient permissions for this resource",
            )

        import lib.github as mod

        monkeypatch.setattr(mod.subprocess, "run", mock_subprocess_run)

        with pytest.raises(CommentPermissionError):
            mod._run_gh(["api", "repos/x/y/issues/1/comments"])

    def test_other_errors_raise_called_process_error(self, monkeypatch):
        def mock_subprocess_run(args, **kwargs):
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout="",
                stderr="rate limit exceeded",
            )

        import lib.github as mod

        monkeypatch.setattr(mod.subprocess, "run", mock_subprocess_run)

        with pytest.raises(subprocess.CalledProcessError):
            mod._run_gh(["api", "repos/x/y/issues/1/comments"])

    def test_success_returns_result(self, monkeypatch):
        def mock_subprocess_run(args, **kwargs):
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout="ok", stderr=""
            )

        import lib.github as mod

        monkeypatch.setattr(mod.subprocess, "run", mock_subprocess_run)

        result = mod._run_gh(["api", "repos/x/y/issues/1/comments"])
        assert result.stdout == "ok"


class TestTransientErrorRetry:
    """Tests for retry logic on transient GitHub API errors (5xx)."""

    def test_503_error_triggers_retry_and_eventually_succeeds(self, monkeypatch):
        call_count = 0

        def mock_subprocess_run(args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=1,
                    stdout="",
                    stderr="gh: HTTP 503: Service Unavailable",
                )
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout='{"id": 123}', stderr=""
            )

        import lib.github as mod

        monkeypatch.setattr(mod.subprocess, "run", mock_subprocess_run)
        # Patch sleep to avoid test delays
        import lib.github_platform as platform

        monkeypatch.setattr(platform.time, "sleep", lambda x: None)

        result = mod._run_gh(["api", "repos/x/y/issues/1/comments"])
        assert result.returncode == 0
        assert call_count == 3

    @pytest.mark.parametrize("error_stderr", [
        "gh: HTTP 502: Bad Gateway",
        "gh: HTTP 504: Gateway Timeout",
        'Post "https://api.github.com/repos/x/y/issues/1/comments": dial tcp 140.82.112.6:443: i/o timeout',
    ])
    def test_5xx_error_triggers_retry(self, monkeypatch, error_stderr):
        call_count = 0

        def mock_subprocess_run(args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=1,
                    stdout="",
                    stderr=error_stderr,
                )
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout="ok", stderr=""
            )

        import lib.github as mod

        monkeypatch.setattr(mod.subprocess, "run", mock_subprocess_run)
        import lib.github_platform as platform

        monkeypatch.setattr(platform.time, "sleep", lambda x: None)

        result = mod._run_gh(["api", "repos/x/y/issues/1/comments"])
        assert result.returncode == 0
        assert call_count == 2

    def test_exhausted_retries_raises_transient_error(self, monkeypatch):
        def mock_subprocess_run(args, **kwargs):
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout="",
                stderr="gh: HTTP 503: Service Unavailable",
            )

        import lib.github as mod

        monkeypatch.setattr(mod.subprocess, "run", mock_subprocess_run)
        import lib.github_platform as platform

        monkeypatch.setattr(platform.time, "sleep", lambda x: None)

        with pytest.raises(mod.TransientGitHubError, match="after 3 attempts"):
            mod._run_gh(["api", "repos/x/y/issues/1/comments"], max_retries=3)

    def test_non_transient_errors_do_not_retry(self, monkeypatch):
        call_count = 0

        def mock_subprocess_run(args, **kwargs):
            nonlocal call_count
            call_count += 1
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout="",
                stderr="rate limit exceeded",
            )

        import lib.github as mod

        monkeypatch.setattr(mod.subprocess, "run", mock_subprocess_run)

        with pytest.raises(subprocess.CalledProcessError):
            mod._run_gh(["api", "repos/x/y/issues/1/comments"])

        assert call_count == 1  # No retries for non-transient errors

    def test_permission_errors_do_not_retry(self, monkeypatch):
        call_count = 0

        def mock_subprocess_run(args, **kwargs):
            nonlocal call_count
            call_count += 1
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout="",
                stderr="HTTP 403: Resource not accessible",
            )

        import lib.github as mod

        monkeypatch.setattr(mod.subprocess, "run", mock_subprocess_run)

        with pytest.raises(CommentPermissionError):
            mod._run_gh(["api", "repos/x/y/issues/1/comments"])

        assert call_count == 1  # No retries for permission errors


class TestTransientErrorHandlingInMain:
    """Tests for how transient errors are handled in main()."""

    def test_transient_error_exits_successfully_to_avoid_merge_blockers(
        self, monkeypatch, tmp_path, capsys
    ):
        body_file = tmp_path / "body.md"
        body_file.write_text("Test body")

        monkeypatch.setattr(
            "sys.argv",
            ["prog", "--repo", "o/r", "--pr", "1", "--marker", "m",
             "--body-file", str(body_file)],
        )

        def mock_upsert(*args, **kwargs):
            import lib.github as mod
            raise mod.TransientGitHubError("HTTP 503 after retries")

        import lib.github as mod

        monkeypatch.setattr(mod, "upsert_pr_comment", mock_upsert)

        # Should exit 0 (not fail the job) to avoid merge blockers
        with pytest.raises(SystemExit) as exc_info:
            mod.main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "GitHub outage" in captured.err

    def test_transient_error_can_exit_nonzero_when_requested(
        self, monkeypatch, tmp_path, capsys
    ):
        body_file = tmp_path / "body.md"
        body_file.write_text("Test body")

        monkeypatch.setattr(
            "sys.argv",
            [
                "prog",
                "--repo",
                "o/r",
                "--pr",
                "1",
                "--marker",
                "m",
                "--body-file",
                str(body_file),
                "--transient-error-exit-code",
                "1",
            ],
        )

        def mock_upsert(*args, **kwargs):
            import lib.github as mod
            raise mod.TransientGitHubError("HTTP 503 after retries")

        import lib.github as mod

        monkeypatch.setattr(mod, "upsert_pr_comment", mock_upsert)

        with pytest.raises(SystemExit) as exc_info:
            mod.main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "GitHub outage" in captured.err

    def test_permission_error_exits_with_error(self, monkeypatch, tmp_path):
        body_file = tmp_path / "body.md"
        body_file.write_text("Test body")

        monkeypatch.setattr(
            "sys.argv",
            ["prog", "--repo", "o/r", "--pr", "1", "--marker", "m",
             "--body-file", str(body_file)],
        )

        def mock_upsert(*args, **kwargs):
            raise CommentPermissionError("no permission")

        import lib.github as mod

        monkeypatch.setattr(mod, "upsert_pr_comment", mock_upsert)

        with pytest.raises(SystemExit) as exc_info:
            mod.main()

        assert exc_info.value.code == 1
