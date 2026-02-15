from __future__ import annotations

import json
import subprocess

from lib.github_reviews import (
    ReviewComment,
    create_pr_review,
    find_review_id_by_marker,
    list_pr_files,
    list_pr_reviews,
)


def test_find_review_id_by_marker() -> None:
    reviews = [
        {"id": 1, "body": "nope"},
        {"id": 2, "body": "<!-- cerberus:council-review sha=abc -->\nhi"},
    ]
    assert (
        find_review_id_by_marker(reviews, "<!-- cerberus:council-review sha=abc -->")
        == 2
    )


def test_list_pr_reviews_parses_json_list(monkeypatch) -> None:
    calls: list[list[str]] = []

    def mock_run_gh(args, *, check=True, max_retries=3, base_delay=1.0):
        calls.append(args)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout='[{"id": 9, "body": "ok"}]',
            stderr="",
        )

    import lib.github as gh

    monkeypatch.setattr(gh, "_run_gh", mock_run_gh)

    reviews = list_pr_reviews("owner/repo", 42)
    assert calls[0][0:2] == ["api", "repos/owner/repo/pulls/42/reviews?per_page=100"]
    assert isinstance(reviews, list)
    assert reviews[0]["id"] == 9


def test_list_pr_files_flattens_paginated_slurp(monkeypatch) -> None:
    def mock_run_gh(args, *, check=True, max_retries=3, base_delay=1.0):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(
                [
                    [{"filename": "a.py", "patch": "@@ -1 +1 @@\n+hi"}],
                    [{"filename": "b.py"}],
                ]
            ),
            stderr="",
        )

    import lib.github as gh

    monkeypatch.setattr(gh, "_run_gh", mock_run_gh)

    files = list_pr_files("owner/repo", 5)
    assert [f.get("filename") for f in files] == ["a.py", "b.py"]


def test_create_pr_review_posts_json_payload(monkeypatch) -> None:
    seen_payload: dict | None = None

    def mock_run_gh(args, *, check=True, max_retries=3, base_delay=1.0):
        nonlocal seen_payload
        assert args[0:4] == ["api", "-X", "POST", "repos/owner/repo/pulls/7/reviews"]
        assert "--input" in args
        payload_path = args[args.index("--input") + 1]
        seen_payload = json.loads(open(payload_path, encoding="utf-8").read())
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout='{"id": 123}', stderr=""
        )

    import lib.github as gh

    monkeypatch.setattr(gh, "_run_gh", mock_run_gh)

    out = create_pr_review(
        repo="owner/repo",
        pr_number=7,
        commit_id="deadbeef",
        body="hello",
        comments=[ReviewComment(path="a.py", position=3, body="c")],
    )

    assert out["id"] == 123
    assert seen_payload is not None
    assert seen_payload["event"] == "COMMENT"
    assert seen_payload["commit_id"] == "deadbeef"
    assert seen_payload["body"] == "hello"
    assert seen_payload["comments"][0]["path"] == "a.py"
    assert seen_payload["comments"][0]["position"] == 3

