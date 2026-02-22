"""GitHub PR comment utilities.

Provides idempotent comment upsert using HTML markers for identification.
Used by per-reviewer comments, verdict, and triage diagnosis.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from pathlib import Path


class CommentPermissionError(Exception):
    """Token lacks pull-requests: write permission."""


class TransientGitHubError(Exception):
    """GitHub API returned a transient error (5xx)."""


def _is_transient_error(stderr: str) -> bool:
    """Check if error is a transient GitHub API error (5xx)."""
    transient_codes = ("502", "503", "504")
    lower_stderr = stderr.lower()
    # Handle both gh CLI format "(http 503)" and raw "HTTP 503" formats
    return any(
        f"(http {code})" in lower_stderr or f"http {code}" in lower_stderr
        for code in transient_codes
    )


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
    for attempt in range(max_retries):
        result = subprocess.run(
            ["gh", *args], capture_output=True, text=True, check=False
        )

        if result.returncode == 0:
            return result

        stderr = (result.stderr or "").lower()

        # Check for permission errors (don't retry these)
        if any(s in stderr for s in ("403", "resource not accessible", "insufficient")):
            raise CommentPermissionError(
                "Unable to post PR comment: token lacks pull-requests: write permission.\n"
                "Add this to your workflow:\n"
                "permissions:\n"
                "  contents: read\n"
                "  pull-requests: write"
            )

        # Check for transient errors (5xx) and retry
        if _is_transient_error(result.stderr or ""):
            if attempt < max_retries - 1:
                # Exponential backoff with jitter: 1s, 2s, 4s + random jitter
                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                print(
                    f"::warning::GitHub API error (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {delay:.1f}s...",
                    file=sys.stderr,
                )
                time.sleep(delay)
                continue
            else:
                # Exhausted retries - raise as transient error
                raise TransientGitHubError(
                    f"GitHub API returned transient error after {max_retries} attempts: "
                    f"{result.stderr}"
                )

        # Non-transient error - fail immediately
        if check:
            raise subprocess.CalledProcessError(
                result.returncode, result.args, result.stdout, result.stderr
            )
        return result

    # The loop must either return or raise. This code should be unreachable.
    raise RuntimeError("_run_gh retry loop exited unexpectedly")


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
    comments: list[dict] = []
    for page in range(1, max_pages + 1):
        endpoint = f"repos/{repo}/issues/{pr_number}/comments?per_page={per_page}&page={page}"
        result = _run_gh(["api", endpoint])
        try:
            payload = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            break
        if not isinstance(payload, list) or not payload:
            break
        comments.extend([c for c in payload if isinstance(c, dict)])

        # Early exit: check if marker found in this page
        if stop_on_marker is not None:
            for comment in payload:
                if isinstance(comment, dict) and stop_on_marker in str(comment.get("body", "")):
                    return comments

        if len(payload) < per_page:
            break
    return comments


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

    if existing_id is not None:
        _run_gh([
            "api",
            f"repos/{repo}/issues/comments/{existing_id}",
            "-X", "PATCH",
            "-F", f"body=@{body_file}",
        ])
    else:
        _run_gh([
            "api",
            f"repos/{repo}/issues/{pr_number}/comments",
            "-F", f"body=@{body_file}",
        ])


def main() -> None:
    """Main."""
    parser = argparse.ArgumentParser(description="Upsert PR comment by HTML marker.")
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--pr", type=int, required=True, help="PR number")
    parser.add_argument("--marker", required=True, help="HTML comment marker")
    parser.add_argument("--body-file", required=True, help="Path to comment body markdown")
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
        # Treat transient errors as non-fatal - warn but don't fail the job
        print(f"::warning::{exc}", file=sys.stderr)
        print(
            "::warning::Comment post failed due to GitHub outage. "
            "Review artifact still uploaded; check logs for review results.",
            file=sys.stderr,
        )
        sys.exit(0)  # Exit successfully to avoid merge blockers
    except subprocess.CalledProcessError as exc:
        print(f"gh command failed: {exc.stderr}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
