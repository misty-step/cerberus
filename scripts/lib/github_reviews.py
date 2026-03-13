"""GitHub PR review utilities.

This module is intentionally small: list reviews, list PR files (with patches),
create a single PR review with inline comments.
"""

from __future__ import annotations

from dataclasses import dataclass

from lib.github import CommentPermissionError, TransientGitHubError
from lib import github_platform as platform


@dataclass(frozen=True)
class ReviewComment:
    """Data class for Review Comment."""
    path: str
    position: int
    body: str

def list_pr_reviews(repo: str, pr_number: int) -> list[dict]:
    """List pr reviews."""
    try:
        return platform.list_pr_reviews(repo, pr_number)
    except platform.GitHubPermissionError as exc:
        raise CommentPermissionError(str(exc)) from exc
    except platform.TransientGitHubError as exc:
        raise TransientGitHubError(str(exc)) from exc


def find_review_id_by_marker(reviews: list[dict], marker: str) -> int | None:
    """Find review id by marker."""
    for review in reviews:
        if not isinstance(review, dict):
            continue
        body = str(review.get("body", "") or "")
        if marker in body:
            rid = review.get("id")
            if isinstance(rid, int):
                return rid
    return None


def list_pr_files(repo: str, pr_number: int) -> list[dict]:
    """List pr files."""
    try:
        return platform.list_pr_files(repo, pr_number)
    except platform.GitHubPermissionError as exc:
        raise CommentPermissionError(str(exc)) from exc
    except platform.TransientGitHubError as exc:
        raise TransientGitHubError(str(exc)) from exc


def create_pr_review(
    *,
    repo: str,
    pr_number: int,
    commit_id: str,
    body: str,
    comments: list[ReviewComment],
) -> dict:
    """Create pr review."""
    try:
        return platform.create_pr_review(
            repo=repo,
            pr_number=pr_number,
            commit_id=commit_id,
            body=body,
            comments=[
                {"path": c.path, "position": c.position, "body": c.body} for c in comments
            ],
        )
    except platform.GitHubPermissionError as exc:
        raise CommentPermissionError(str(exc)) from exc
    except platform.TransientGitHubError as exc:
        raise TransientGitHubError(str(exc)) from exc
