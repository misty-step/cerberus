"""GitHub PR comment utilities.

Provides idempotent comment upsert using HTML markers for identification.
Used by per-reviewer comments, verdict, and triage diagnosis.
"""
from __future__ import annotations

import argparse
import importlib
import subprocess
import sys
from pathlib import Path


def _ensure_scripts_import_root() -> None:
    """Allow direct execution from scripts/lib without caller PYTHONPATH tweaks."""
    if __package__ not in (None, ""):
        return
    scripts_dir = Path(__file__).resolve().parent.parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


_ensure_scripts_import_root()

_github_platform = importlib.import_module("lib.github_platform")
PlatformPermissionError = _github_platform.GitHubPermissionError
PlatformTransientGitHubError = _github_platform.TransientGitHubError
create_issue_comment = _github_platform.create_issue_comment
fetch_issue_comments = _github_platform.fetch_issue_comments
is_transient_error = _github_platform.is_transient_error
run_gh = _github_platform.run_gh
update_issue_comment = _github_platform.update_issue_comment


class CommentPermissionError(Exception):
    """Token lacks pull-requests: write permission."""


class TransientGitHubError(Exception):
    """GitHub API returned a transient error (5xx)."""


def _is_transient_error(stderr: str) -> bool:
    """Check if error is a transient GitHub API or network error."""
    return is_transient_error(stderr)


def _run_gh(
    args: list[str],
    *,
    check: bool = True,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> subprocess.CompletedProcess[str]:
    """Run a gh CLI command with retry logic for transient errors.

    Args:
        args: Arguments to pass to gh CLI
        check: Whether to raise on non-zero exit code
        max_retries: Maximum number of retry attempts for transient errors
        base_delay: Base delay in seconds between retries (uses exponential backoff)

    Returns:
        CompletedProcess result from the gh command

    Raises:
        CommentPermissionError: Token lacks pull-requests: write permission
        TransientGitHubError: GitHub API returned 5xx after all retries
        subprocess.CalledProcessError: Other gh CLI failures
    """
    try:
        return run_gh(
            args,
            check=check,
            max_retries=max_retries,
            base_delay=base_delay,
        )
    except PlatformPermissionError as exc:
        raise CommentPermissionError(str(exc)) from exc
    except PlatformTransientGitHubError as exc:
        raise TransientGitHubError(str(exc)) from exc


def _reraise_platform_error(exc: Exception) -> None:
    """Map platform exceptions onto this module's public exception contract."""

    if isinstance(exc, PlatformPermissionError):
        raise CommentPermissionError(str(exc)) from exc
    if isinstance(exc, PlatformTransientGitHubError):
        raise TransientGitHubError(str(exc)) from exc
    raise exc


def fetch_comments(
    repo: str,
    pr_number: int,
    *,
    per_page: int = 100,
    max_pages: int = 20,
    stop_on_marker: str | None = None,
) -> list[dict]:
    """Fetch all issue comments for a PR (paginated).

    Args:
        repo: Repository in owner/repo format
        pr_number: Pull request number
        per_page: Number of comments per page (max 100)
        max_pages: Maximum number of pages to fetch
        stop_on_marker: If provided, stop pagination early when a comment
            containing this marker is found. Useful for finding specific
            comments without fetching all pages on noisy PRs.

    Returns:
        List of comment dictionaries fetched up to the stopping point
    """
    try:
        return fetch_issue_comments(
            repo,
            pr_number,
            per_page=per_page,
            max_pages=max_pages,
            stop_on_marker=stop_on_marker,
        )
    except (PlatformPermissionError, PlatformTransientGitHubError) as exc:
        _reraise_platform_error(exc)


def find_comment_by_marker(comments: list[dict], marker: str) -> int | None:
    """Find the first comment containing the marker, return its numeric ID."""
    for comment in comments:
        body = str(comment.get("body", ""))
        if marker in body:
            comment_id = comment.get("id")
            if isinstance(comment_id, int):
                return comment_id
    return None


def find_comment_url_by_marker(comments: list[dict], marker: str) -> str | None:
    """Find the first comment containing the marker, return its html_url if present."""
    for comment in comments:
        body = str(comment.get("body", ""))
        if marker not in body:
            continue
        url = comment.get("html_url")
        return url if isinstance(url, str) and url.strip() else None
    return None


def upsert_pr_comment(
    *,
    repo: str,
    pr_number: int,
    marker: str,
    body_file: str,
    comments: list[dict] | None = None,
) -> None:
    """Find existing PR comment by HTML marker, update or create.

    If comments is provided, searches that list instead of fetching from API.

    Raises:
        CommentPermissionError: Token lacks pull-requests: write permission.
        TransientGitHubError: GitHub API returned 5xx after retries.
        subprocess.CalledProcessError: Other gh CLI failures.
    """
    if comments is None:
        comments = fetch_comments(repo, pr_number)

    existing_id = find_comment_by_marker(comments, marker)

    try:
        if existing_id is not None:
            update_issue_comment(repo=repo, comment_id=existing_id, body_file=body_file)
        else:
            create_issue_comment(repo=repo, number=pr_number, body_file=body_file)
    except (PlatformPermissionError, PlatformTransientGitHubError) as exc:
        _reraise_platform_error(exc)


def main() -> None:
    """Main."""
    parser = argparse.ArgumentParser(description="Upsert PR comment by HTML marker.")
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--pr", type=int, required=True, help="PR number")
    parser.add_argument("--marker", required=True, help="HTML comment marker")
    parser.add_argument("--body-file", required=True, help="Path to comment body markdown")
    parser.add_argument(
        "--transient-error-exit-code",
        type=int,
        choices=(0, 1),
        default=0,
        help="Exit code to use when comment posting fails due to transient GitHub/network errors.",
    )
    args = parser.parse_args()

    if not Path(args.body_file).exists():
        print(f"body file not found: {args.body_file}", file=sys.stderr)
        sys.exit(2)

    try:
        upsert_pr_comment(
            repo=args.repo,
            pr_number=args.pr,
            marker=args.marker,
            body_file=args.body_file,
        )
    except CommentPermissionError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        sys.exit(1)
    except TransientGitHubError as exc:
        print(f"::warning::{exc}", file=sys.stderr)
        print(
            "::warning::Comment post failed due to GitHub outage. "
            "Review artifact still uploaded; check logs for review results.",
            file=sys.stderr,
        )
        sys.exit(args.transient_error_exit_code)
    except subprocess.CalledProcessError as exc:
        print(f"gh command failed: {exc.stderr}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
