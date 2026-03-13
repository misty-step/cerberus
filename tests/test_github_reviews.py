from __future__ import annotations

import pytest

from lib.github import (
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


def test_find_review_id_by_marker_continues_after_non_integer_match() -> None:
    reviews = [
        {"id": "RV_x", "body": "<!-- cerberus:council-review sha=abc -->\nfirst"},
        {"id": 2, "body": "<!-- cerberus:council-review sha=abc -->\nsecond"},
    ]

    assert (
        find_review_id_by_marker(reviews, "<!-- cerberus:council-review sha=abc -->")
        == 2
    )


def test_list_pr_reviews_parses_json_list(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    def fake_list_pr_reviews(repo: str, pr_number: int):
        calls.append((repo, pr_number))
        return [{"id": 9, "body": "ok"}]

    import lib.github_platform as platform

    monkeypatch.setattr(platform, "list_pr_reviews", fake_list_pr_reviews)

    reviews = list_pr_reviews("owner/repo", 42)
    assert calls == [("owner/repo", 42)]
    assert isinstance(reviews, list)
    assert reviews[0]["id"] == 9


def test_list_pr_files_flattens_paginated_slurp(monkeypatch) -> None:
    def fake_list_pr_files(repo: str, pr_number: int):
        assert (repo, pr_number) == ("owner/repo", 5)
        return [{"filename": "a.py", "patch": "@@ -1 +1 @@\n+hi"}, {"filename": "b.py"}]

    import lib.github_platform as platform

    monkeypatch.setattr(platform, "list_pr_files", fake_list_pr_files)

    files = list_pr_files("owner/repo", 5)
    assert [f.get("filename") for f in files] == ["a.py", "b.py"]


def test_create_pr_review_posts_json_payload(monkeypatch) -> None:
    seen: dict | None = None

    def fake_create_pr_review(*, repo: str, pr_number: int, commit_id: str, body: str, comments: list[dict]):
        nonlocal seen
        seen = {
            "repo": repo,
            "pr_number": pr_number,
            "commit_id": commit_id,
            "body": body,
            "comments": comments,
        }
        return {"id": 123}

    import lib.github_platform as platform

    monkeypatch.setattr(platform, "create_pr_review", fake_create_pr_review)

    out = create_pr_review(
        repo="owner/repo",
        pr_number=7,
        commit_id="deadbeef",
        body="hello",
        comments=[ReviewComment(path="a.py", position=3, body="c")],
    )

    assert out["id"] == 123
    assert seen == {
        "repo": "owner/repo",
        "pr_number": 7,
        "commit_id": "deadbeef",
        "body": "hello",
        "comments": [{"path": "a.py", "position": 3, "body": "c"}],
    }


def test_list_pr_reviews_translates_permission_errors(monkeypatch) -> None:
    import lib.github_platform as platform
    import lib.github as mod

    def fake_list_pr_reviews(repo: str, pr_number: int):
        raise platform.GitHubPermissionError("no permission")

    monkeypatch.setattr(platform, "list_pr_reviews", fake_list_pr_reviews)

    with pytest.raises(mod.CommentPermissionError, match="no permission"):
        mod.list_pr_reviews("owner/repo", 42)


def test_list_pr_reviews_translates_transient_errors(monkeypatch) -> None:
    import lib.github_platform as platform
    import lib.github as mod

    def fake_list_pr_reviews(repo: str, pr_number: int):
        raise platform.TransientGitHubError("temporary")

    monkeypatch.setattr(platform, "list_pr_reviews", fake_list_pr_reviews)

    with pytest.raises(mod.TransientGitHubError, match="temporary"):
        mod.list_pr_reviews("owner/repo", 42)


def test_list_pr_files_translates_permission_errors(monkeypatch) -> None:
    import lib.github_platform as platform
    import lib.github as mod

    def fake_list_pr_files(repo: str, pr_number: int):
        raise platform.GitHubPermissionError("no permission")

    monkeypatch.setattr(platform, "list_pr_files", fake_list_pr_files)

    with pytest.raises(mod.CommentPermissionError, match="no permission"):
        mod.list_pr_files("owner/repo", 5)


def test_list_pr_files_translates_transient_errors(monkeypatch) -> None:
    import lib.github_platform as platform
    import lib.github as mod

    def fake_list_pr_files(repo: str, pr_number: int):
        raise platform.TransientGitHubError("temporary")

    monkeypatch.setattr(platform, "list_pr_files", fake_list_pr_files)

    with pytest.raises(mod.TransientGitHubError, match="temporary"):
        mod.list_pr_files("owner/repo", 5)


def test_create_pr_review_translates_permission_errors(monkeypatch) -> None:
    import lib.github_platform as platform
    import lib.github as mod

    def fake_create_pr_review(**kwargs):
        raise platform.GitHubPermissionError("no permission")

    monkeypatch.setattr(platform, "create_pr_review", fake_create_pr_review)

    with pytest.raises(mod.CommentPermissionError, match="no permission"):
        mod.create_pr_review(
            repo="owner/repo",
            pr_number=7,
            commit_id="deadbeef",
            body="hello",
            comments=[],
        )


def test_create_pr_review_translates_transient_errors(monkeypatch) -> None:
    import lib.github_platform as platform
    import lib.github as mod

    def fake_create_pr_review(**kwargs):
        raise platform.TransientGitHubError("temporary")

    monkeypatch.setattr(platform, "create_pr_review", fake_create_pr_review)

    with pytest.raises(mod.TransientGitHubError, match="temporary"):
        mod.create_pr_review(
            repo="owner/repo",
            pr_number=7,
            commit_id="deadbeef",
            body="hello",
            comments=[],
        )
