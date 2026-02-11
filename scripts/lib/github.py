"""GitHub PR comment utilities.

Provides idempotent comment upsert using HTML markers for identification.
Used by per-reviewer comments, council verdict, and triage diagnosis.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


class CommentPermissionError(Exception):
    """Token lacks pull-requests: write permission."""


def _run_gh(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a gh CLI command."""
    result = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        stderr = (result.stderr or "").lower()
        if any(s in stderr for s in ("403", "resource not accessible", "insufficient")):
            raise CommentPermissionError(
                "Unable to post PR comment: token lacks pull-requests: write permission.\n"
                "Add this to your workflow:\n"
                "permissions:\n"
                "  contents: read\n"
                "  pull-requests: write"
            )
        raise subprocess.CalledProcessError(
            result.returncode, result.args, result.stdout, result.stderr
        )
    return result


def fetch_comments(repo: str, pr_number: int) -> list[dict]:
    """Fetch all comments on a PR."""
    result = _run_gh(["api", f"repos/{repo}/issues/{pr_number}/comments?per_page=100"])
    return json.loads(result.stdout)


def find_comment_by_marker(comments: list[dict], marker: str) -> int | None:
    """Find the first comment containing the marker, return its numeric ID."""
    for comment in comments:
        body = str(comment.get("body", ""))
        if marker in body:
            comment_id = comment.get("id")
            if isinstance(comment_id, int):
                return comment_id
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
    except subprocess.CalledProcessError as exc:
        print(f"gh command failed: {exc.stderr}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
