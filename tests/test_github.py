"""Tests for lib.github PR comment upsert."""
from __future__ import annotations

import subprocess

import pytest

from lib.github import (
    CommentPermissionError,
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
