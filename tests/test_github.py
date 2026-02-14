"""Tests for lib.github PR comment upsert."""
from __future__ import annotations

import subprocess

import pytest

from lib.github import (
    CommentPermissionError,
    TransientGitHubError,
    find_comment_by_marker,
    upsert_pr_comment,
)


class TestFindCommentByMarker:
    def test_finds_matching_comment(self):
        comments = [
            {"id": 100, "body": "unrelated comment"},
            {"id": 200, "body": "<!-- cerberus:council -->\nCouncil verdict"},
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
            {"id": 200, "body": "<!-- cerberus:council -->\nCouncil verdict"},
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


class TestUpsertPrComment:
    def test_creates_comment_when_none_exists(self, monkeypatch, tmp_path):
        body_file = tmp_path / "body.md"
        body_file.write_text("Test body")

        calls = []

        def mock_run_gh(args, *, check=True):
            calls.append(args)
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        import lib.github as mod

        monkeypatch.setattr(mod, "_run_gh", mock_run_gh)

        upsert_pr_comment(
            repo="owner/repo",
            pr_number=42,
            marker="<!-- test -->",
            body_file=str(body_file),
            comments=[],
        )

        assert len(calls) == 1
        assert calls[0] == [
            "api",
            "repos/owner/repo/issues/42/comments",
            "-F",
            f"body=@{body_file}",
        ]

    def test_updates_existing_comment(self, monkeypatch, tmp_path):
        body_file = tmp_path / "body.md"
        body_file.write_text("Updated body")

        calls = []

        def mock_run_gh(args, *, check=True):
            calls.append(args)
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        import lib.github as mod

        monkeypatch.setattr(mod, "_run_gh", mock_run_gh)

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

        assert len(calls) == 1
        assert calls[0] == [
            "api",
            "repos/owner/repo/issues/comments/555",
            "-X",
            "PATCH",
            "-F",
            f"body=@{body_file}",
        ]

    def test_fetches_comments_when_not_provided(self, monkeypatch, tmp_path):
        body_file = tmp_path / "body.md"
        body_file.write_text("Body")

        calls = []

        def mock_run_gh(args, *, check=True):
            calls.append(args)
            if args[1].endswith("per_page=100") and "-F" not in args:
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=0,
                    stdout='[{"id": 999, "body": "<!-- test -->\\nContent"}]',
                    stderr="",
                )
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        import lib.github as mod

        monkeypatch.setattr(mod, "_run_gh", mock_run_gh)

        upsert_pr_comment(
            repo="owner/repo",
            pr_number=42,
            marker="<!-- test -->",
            body_file=str(body_file),
        )

        assert len(calls) == 2
        assert calls[1] == [
            "api",
            "repos/owner/repo/issues/comments/999",
            "-X",
            "PATCH",
            "-F",
            f"body=@{body_file}",
        ]

    def test_multiple_markers_dont_conflict(self, monkeypatch, tmp_path):
        body_file = tmp_path / "body.md"
        body_file.write_text("Body for council")

        calls = []

        def mock_run_gh(args, *, check=True):
            calls.append(args)
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        import lib.github as mod

        monkeypatch.setattr(mod, "_run_gh", mock_run_gh)

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

        assert calls[0] == [
            "api",
            "repos/owner/repo/issues/comments/200",
            "-X",
            "PATCH",
            "-F",
            f"body=@{body_file}",
        ]

    def test_permission_denied_raises(self, monkeypatch, tmp_path):
        body_file = tmp_path / "body.md"
        body_file.write_text("Body")

        def mock_run_gh(args, *, check=True):
            raise CommentPermissionError("no permission")

        import lib.github as mod

        monkeypatch.setattr(mod, "_run_gh", mock_run_gh)

        with pytest.raises(CommentPermissionError):
            upsert_pr_comment(
                repo="owner/repo",
                pr_number=42,
                marker="<!-- test -->",
                body_file=str(body_file),
                comments=[],
            )


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
        monkeypatch.setattr(mod.time, "sleep", lambda x: None)

        result = mod._run_gh(["api", "repos/x/y/issues/1/comments"])
        assert result.returncode == 0
        assert call_count == 3

    @pytest.mark.parametrize("error_stderr", [
        "gh: HTTP 502: Bad Gateway",
        "gh: HTTP 504: Gateway Timeout",
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
        monkeypatch.setattr(mod.time, "sleep", lambda x: None)

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
        monkeypatch.setattr(mod.time, "sleep", lambda x: None)

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
