"""GitHub PR review utilities.

This module is intentionally small: list reviews, list PR files (with patches),
create a single PR review with inline comments.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass

from lib import github as gh


@dataclass(frozen=True)
class ReviewComment:
    path: str
    position: int
    body: str


def list_pr_reviews(repo: str, pr_number: int) -> list[dict]:
    result = gh._run_gh(["api", f"repos/{repo}/pulls/{pr_number}/reviews?per_page=100"])
    data = json.loads(result.stdout)
    return data if isinstance(data, list) else []


def find_review_id_by_marker(reviews: list[dict], marker: str) -> int | None:
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
    # --paginate without --slurp does not produce valid JSON.
    result = gh._run_gh(
        [
            "api",
            "--paginate",
            "--slurp",
            f"repos/{repo}/pulls/{pr_number}/files?per_page=100",
        ]
    )
    pages = json.loads(result.stdout)
    if not isinstance(pages, list):
        return []
    files: list[dict] = []
    for page in pages:
        if isinstance(page, list):
            for item in page:
                if isinstance(item, dict):
                    files.append(item)
    return files


def create_pr_review(
    *,
    repo: str,
    pr_number: int,
    commit_id: str,
    body: str,
    comments: list[ReviewComment],
) -> dict:
    payload: dict[str, object] = {
        "event": "COMMENT",
        "commit_id": commit_id,
        "body": body,
    }
    if comments:
        payload["comments"] = [
            {"path": c.path, "position": c.position, "body": c.body} for c in comments
        ]

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        json.dump(payload, handle)
        handle.flush()
        tmp_path = handle.name

    result = gh._run_gh(
        [
            "api",
            "-X",
            "POST",
            f"repos/{repo}/pulls/{pr_number}/reviews",
            "--input",
            tmp_path,
        ]
    )
    data = json.loads(result.stdout or "{}")
    return data if isinstance(data, dict) else {}

