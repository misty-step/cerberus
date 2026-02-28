import importlib.util
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "post-verdict-review.py"


def _load():
    spec = importlib.util.spec_from_file_location("post_verdict_review", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


post_verdict_review = _load()


def test_collect_inline_findings_filters_dedupes_and_merges() -> None:
    verdict_data = {
        "reviewers": [
            {
                "reviewer": "APOLLO",
                "perspective": "correctness",
                "reviewer_description": "Correctness & Logic — Find the bug",
                "findings": [
                    {
                        "severity": "minor",
                        "category": "style",
                        "file": "x.py",
                        "line": 1,
                        "title": "nit",
                        "description": "minor",
                        "suggestion": "",
                        "evidence": "",
                    },
                    {
                        "severity": "major",
                        "category": "Bug",
                        "file": "x.py",
                        "line": 10,
                        "title": "Same  issue",
                        "description": "short",
                        "suggestion": "s",
                        "evidence": "e",
                    },
                ],
            },
            {
                "reviewer": "SENTINEL",
                "perspective": "security",
                "reviewer_description": "Security & Threat Model — Think like an attacker",
                "findings": [
                    {
                        "severity": "critical",
                        "category": "bug",
                        "file": "x.py",
                        "line": 10,
                        "title": "same issue",
                        "description": "this description is longer",
                        "suggestion": "this suggestion is longer too",
                        "evidence": "evidence line 1\nline 2",
                    },
                    {
                        "severity": "major",
                        "category": "bug",
                        "file": "",
                        "line": 99,
                        "title": "missing file is ignored",
                        "description": "",
                        "suggestion": "",
                        "evidence": "",
                    },
                ],
            },
        ]
    }

    out = post_verdict_review.collect_inline_findings(verdict_data)
    assert len(out) == 1
    finding = out[0]
    assert finding["file"] == "x.py"
    assert finding["line"] == 10
    assert finding["severity"] == "critical"  # worst wins
    assert finding["reviewers"] == ["Correctness & Logic", "Security & Threat Model"]
    assert finding["description"] == "this description is longer"
    assert finding["suggestion"] == "this suggestion is longer too"
    assert finding["evidence"] == "evidence line 1\nline 2"


def test_render_inline_comment_includes_collapsed_evidence() -> None:
    finding = {
        "severity": "critical",
        "category": "security",
        "title": "Constant-time compare required",
        "reviewers": ["SENTINEL", "APOLLO", "ATHENA", "VULCAN"],
        "description": "Timing attack risk.",
        "suggestion": "Use constant-time compare.",
        "evidence": "if sig == expected: ok()",
    }

    body = post_verdict_review.render_inline_comment(finding)

    assert "(SENTINEL, APOLLO, +2)" in body
    assert "Suggestion: Use constant-time compare." in body
    assert "<details>" in body
    assert "<summary>Evidence</summary>" in body
    assert "```text" in body
    assert "if sig == expected: ok()" in body


def _argv(*extra: str) -> list[str]:
    return ["post-verdict-review.py", "--repo", "owner/repo", "--pr", "7", *extra]


def test_reviewer_label_falls_back_to_perspective_or_unknown() -> None:
    assert (
        post_verdict_review.reviewer_label(
            {"reviewer_description": "", "perspective": "threat_model"}
        )
        == "Threat Model"
    )
    assert post_verdict_review.reviewer_label({}) == "unknown"


def test_fail_exits_with_code_and_message(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        post_verdict_review.fail("boom", code=9)
    assert exc.value.code == 9
    assert "post-verdict-review: boom" in capsys.readouterr().err


def test_warn_emits_github_warning(capsys) -> None:
    post_verdict_review.warn("warn-msg")
    assert "::warning::warn-msg" in capsys.readouterr().err


def test_notice_emits_github_notice(capsys) -> None:
    post_verdict_review.notice("notice-msg")
    assert "::notice::notice-msg" in capsys.readouterr().err


def test_as_int_returns_none_for_non_numeric() -> None:
    assert post_verdict_review.as_int(None) is None
    assert post_verdict_review.as_int("x") is None


def test_normalize_path_strips_diff_prefixes() -> None:
    assert post_verdict_review.normalize_path("a/src/app.py") == "src/app.py"
    assert post_verdict_review.normalize_path("b/src/app.py") == "src/app.py"
    assert post_verdict_review.normalize_path("./src/app.py") == "src/app.py"


def test_review_marker_uses_short_sha_or_placeholder() -> None:
    assert post_verdict_review.review_marker("") == "<!-- cerberus:verdict-review sha=<head-sha> -->"
    assert "sha=abcdef123456" in post_verdict_review.review_marker("abcdef1234567890deadbeef")


def test_truncate_appends_ellipsis_when_over_limit() -> None:
    assert post_verdict_review.truncate("abc", max_len=5) == "abc"
    out = post_verdict_review.truncate("abcdef", max_len=5)
    assert out.endswith("…")
    assert len(out) == 5


def test_read_json_missing_or_invalid_exits(tmp_path) -> None:
    with pytest.raises(SystemExit) as exc:
        post_verdict_review.read_json(tmp_path / "missing.json")
    assert exc.value.code == 2

    bad = tmp_path / "bad.json"
    bad.write_text("{bad json}", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        post_verdict_review.read_json(bad)
    assert exc.value.code == 2


def test_read_json_returns_empty_dict_for_non_dict_json(tmp_path) -> None:
    """Valid JSON that isn't an object (e.g. a list) should return {}."""
    list_json = tmp_path / "list.json"
    list_json.write_text("[1, 2, 3]", encoding="utf-8")
    assert post_verdict_review.read_json(list_json) == {}


def test_collect_inline_findings_handles_invalid_shapes_and_line_zero() -> None:
    assert post_verdict_review.collect_inline_findings({}) == []
    assert post_verdict_review.collect_inline_findings({"reviewers": "bad"}) == []

    verdict_data = {
        "reviewers": [
            "not-a-dict",
            {"reviewer_description": "Role — Desc", "findings": "not-a-list"},
            {
                "reviewer_description": "Role — Desc",
                "findings": [
                    {
                        "severity": "major",
                        "category": "bug",
                        "file": "x.py",
                        "line": 0,
                        "title": "ignored",
                    }
                ],
            },
        ]
    }
    assert post_verdict_review.collect_inline_findings(verdict_data) == []


def test_render_inline_comment_omits_empty_sections() -> None:
    body = post_verdict_review.render_inline_comment(
        {
            "severity": "major",
            "category": "bug",
            "title": "Minimal finding",
            "reviewers": ["APOLLO"],
            "description": "",
            "suggestion": "",
            "evidence": "",
        }
    )
    assert "Minimal finding" in body
    assert "Suggestion:" not in body
    assert "<details>" not in body


def test_build_patch_index_maps_current_and_previous_filenames() -> None:
    files = [
        {
            "filename": "src/new.py",
            "previous_filename": "src/old.py",
            "patch": "@@ -1,0 +1,2 @@\n+first\n+second",
        },
        {"filename": "", "patch": "@@ -1 +1 @@\n-a\n+b"},
        {"filename": "docs/readme.md", "patch": None},
    ]
    with patch.object(post_verdict_review, "list_pr_files", return_value=files):
        index = post_verdict_review.build_patch_index("owner/repo", 7)

    assert "src/new.py" in index
    assert "src/old.py" in index
    canonical, mapping = index["src/new.py"]
    assert canonical == "src/new.py"
    assert mapping.get(1) == 2
    assert index["src/old.py"][0] == "src/new.py"


def test_main_missing_head_sha_calls_fail() -> None:
    with (
        patch.object(post_verdict_review.sys, "argv", _argv()),
        patch.dict(post_verdict_review.os.environ, {}, clear=True),
        patch.object(post_verdict_review, "fail", side_effect=SystemExit(2)) as fail_mock,
    ):
        with pytest.raises(SystemExit) as exc:
            post_verdict_review.main()
    assert exc.value.code == 2
    fail_mock.assert_called_once()
    assert "missing head sha" in fail_mock.call_args.args[0]


def test_main_returns_early_when_review_already_posted() -> None:
    with (
        patch.object(post_verdict_review.sys, "argv", _argv("--head-sha", "1234567890abcdef")),
        patch.object(post_verdict_review, "list_pr_reviews", return_value=[{"id": 1}]),
        patch.object(post_verdict_review, "find_review_id_by_marker", return_value=123),
        patch.object(post_verdict_review, "read_json") as read_json_mock,
        patch.object(post_verdict_review, "notice") as notice_mock,
    ):
        post_verdict_review.main()
    read_json_mock.assert_not_called()
    assert "already posted" in notice_mock.call_args.args[0]


def test_main_returns_early_when_no_eligible_findings() -> None:
    with (
        patch.object(post_verdict_review.sys, "argv", _argv("--head-sha", "abcdef123456")),
        patch.object(post_verdict_review, "list_pr_reviews", return_value=[]),
        patch.object(post_verdict_review, "find_review_id_by_marker", return_value=None),
        patch.object(post_verdict_review, "read_json", return_value={"verdict": "PASS"}),
        patch.object(post_verdict_review, "collect_inline_findings", return_value=[]),
        patch.object(post_verdict_review, "build_patch_index") as build_patch_index_mock,
        patch.object(post_verdict_review, "notice") as notice_mock,
    ):
        post_verdict_review.main()
    build_patch_index_mock.assert_not_called()
    assert "No critical/major findings eligible" in notice_mock.call_args.args[0]


def test_main_returns_early_when_no_inline_comments_can_anchor() -> None:
    finding = {
        "severity": "major",
        "category": "bug",
        "file": "src/app.py",
        "line": 12,
        "title": "Anchor me",
    }
    with (
        patch.object(post_verdict_review.sys, "argv", _argv("--head-sha", "abcdef123456")),
        patch.object(post_verdict_review, "list_pr_reviews", return_value=[]),
        patch.object(post_verdict_review, "find_review_id_by_marker", return_value=None),
        patch.object(post_verdict_review, "read_json", return_value={"verdict": "WARN"}),
        patch.object(post_verdict_review, "collect_inline_findings", return_value=[finding]),
        patch.object(post_verdict_review, "build_patch_index", return_value={}),
        patch.object(post_verdict_review, "notice") as notice_mock,
    ):
        post_verdict_review.main()
    msg = notice_mock.call_args.args[0]
    assert "No inline comments could be anchored" in msg
    assert "unanchored" in msg


def test_main_posts_review_with_inline_comments() -> None:
    sha = "abcdef1234567890"
    finding = {
        "severity": "critical",
        "category": "security",
        "file": "src/app.py",
        "line": 12,
        "title": "Critical issue",
        "description": "desc",
        "suggestion": "",
        "evidence": "",
        "reviewers": ["SENTINEL"],
    }
    verdict_data = {"verdict": "FAIL", "summary": "must fix"}
    with (
        patch.object(post_verdict_review.sys, "argv", _argv("--head-sha", sha)),
        patch.object(post_verdict_review, "list_pr_reviews", return_value=[]),
        patch.object(post_verdict_review, "find_review_id_by_marker", return_value=None),
        patch.object(post_verdict_review, "read_json", return_value=verdict_data),
        patch.object(post_verdict_review, "collect_inline_findings", return_value=[finding]),
        patch.object(
            post_verdict_review,
            "build_patch_index",
            return_value={"src/app.py": ("src/app.py", {12: 7})},
        ),
        patch.object(
            post_verdict_review,
            "fetch_comments",
            return_value=[{"body": "<!-- cerberus:verdict -->"}],
        ),
        patch.object(
            post_verdict_review,
            "find_comment_url_by_marker",
            return_value="https://example.com/verdict",
        ),
        patch.object(post_verdict_review, "create_pr_review") as create_mock,
        patch.object(post_verdict_review, "notice") as notice_mock,
    ):
        post_verdict_review.main()

    kwargs = create_mock.call_args.kwargs
    assert kwargs["repo"] == "owner/repo"
    assert kwargs["pr_number"] == 7
    assert kwargs["commit_id"] == sha
    assert len(kwargs["comments"]) == 1
    assert kwargs["comments"][0].path == "src/app.py"
    assert kwargs["comments"][0].position == 7
    assert "<!-- cerberus:verdict-review sha=abcdef123456 -->" in kwargs["body"]
    assert "Cerberus verdict: `FAIL` (must fix)" in kwargs["body"]
    assert "Posted Cerberus PR review" in notice_mock.call_args.args[0]


def test_main_respects_per_file_cap_and_notes_omitted() -> None:
    findings = [
        {"severity": "major", "category": "bug", "file": "src/app.py", "line": i, "title": f"t{i}"}
        for i in range(1, 5)
    ]
    with (
        patch.object(post_verdict_review.sys, "argv", _argv("--head-sha", "abcdef123456")),
        patch.object(post_verdict_review, "list_pr_reviews", return_value=[]),
        patch.object(post_verdict_review, "find_review_id_by_marker", return_value=None),
        patch.object(post_verdict_review, "read_json", return_value={"verdict": "WARN"}),
        patch.object(post_verdict_review, "collect_inline_findings", return_value=findings),
        patch.object(
            post_verdict_review,
            "build_patch_index",
            return_value={"src/app.py": ("src/app.py", {1: 11, 2: 12, 3: 13, 4: 14})},
        ),
        patch.object(post_verdict_review, "fetch_comments", return_value=[]),
        patch.object(post_verdict_review, "find_comment_url_by_marker", return_value=""),
        patch.object(post_verdict_review, "create_pr_review") as create_mock,
    ):
        post_verdict_review.main()

    kwargs = create_mock.call_args.kwargs
    assert len(kwargs["comments"]) == 3
    assert "top 3/4 anchored" in kwargs["body"]
    assert "verdict report (timeline)" in kwargs["body"]


def test_main_skips_findings_outside_diff_hunk() -> None:
    """Findings whose line is in the file but not in the diff hunk are silently skipped."""
    finding = {
        "severity": "major",
        "category": "bug",
        "file": "src/app.py",
        "line": 99,
        "title": "Out of hunk",
    }
    # Patch index knows the file but line 99 has no diff position
    with (
        patch.object(post_verdict_review.sys, "argv", _argv("--head-sha", "abcdef123456")),
        patch.object(post_verdict_review, "list_pr_reviews", return_value=[]),
        patch.object(post_verdict_review, "find_review_id_by_marker", return_value=None),
        patch.object(post_verdict_review, "read_json", return_value={"verdict": "WARN"}),
        patch.object(post_verdict_review, "collect_inline_findings", return_value=[finding]),
        patch.object(
            post_verdict_review,
            "build_patch_index",
            return_value={"src/app.py": ("src/app.py", {10: 2, 20: 5})},
        ),
        patch.object(post_verdict_review, "notice") as notice_mock,
    ):
        post_verdict_review.main()
    msg = notice_mock.call_args.args[0]
    assert "No inline comments could be anchored" in msg


def test_main_warns_on_comment_lookup_failure_but_still_posts() -> None:
    finding = {"severity": "major", "category": "bug", "file": "src/app.py", "line": 10, "title": "t"}
    with (
        patch.object(post_verdict_review.sys, "argv", _argv("--head-sha", "abcdef123456")),
        patch.object(post_verdict_review, "list_pr_reviews", return_value=[]),
        patch.object(post_verdict_review, "find_review_id_by_marker", return_value=None),
        patch.object(post_verdict_review, "read_json", return_value={"verdict": "WARN"}),
        patch.object(post_verdict_review, "collect_inline_findings", return_value=[finding]),
        patch.object(
            post_verdict_review,
            "build_patch_index",
            return_value={"src/app.py": ("src/app.py", {10: 2})},
        ),
        patch.object(
            post_verdict_review,
            "fetch_comments",
            side_effect=post_verdict_review.TransientGitHubError("temporary"),
        ),
        patch.object(post_verdict_review, "create_pr_review") as create_mock,
        patch.object(post_verdict_review, "warn") as warn_mock,
    ):
        post_verdict_review.main()
    create_mock.assert_called_once()
    assert "Unable to fetch verdict comment URL" in warn_mock.call_args.args[0]


def test_main_handles_comment_permission_error() -> None:
    with (
        patch.object(post_verdict_review.sys, "argv", _argv("--head-sha", "abcdef123456")),
        patch.object(
            post_verdict_review,
            "list_pr_reviews",
            side_effect=post_verdict_review.CommentPermissionError("no permission"),
        ),
        patch.object(post_verdict_review, "warn") as warn_mock,
    ):
        post_verdict_review.main()
    warn_mock.assert_called_once_with("no permission")


def test_main_handles_transient_github_error() -> None:
    with (
        patch.object(post_verdict_review.sys, "argv", _argv("--head-sha", "abcdef123456")),
        patch.object(
            post_verdict_review,
            "list_pr_reviews",
            side_effect=post_verdict_review.TransientGitHubError("503"),
        ),
        patch.object(post_verdict_review, "warn") as warn_mock,
    ):
        post_verdict_review.main()
    warn_mock.assert_called_once_with("503")


def test_main_warns_when_create_pr_review_raises_calledprocesserror() -> None:
    finding = {"severity": "major", "category": "bug", "file": "src/app.py", "line": 9, "title": "t"}
    error = subprocess.CalledProcessError(1, ["gh", "api"], stderr="boom")
    with (
        patch.object(post_verdict_review.sys, "argv", _argv("--head-sha", "abcdef123456")),
        patch.object(post_verdict_review, "list_pr_reviews", return_value=[]),
        patch.object(post_verdict_review, "find_review_id_by_marker", return_value=None),
        patch.object(post_verdict_review, "read_json", return_value={"verdict": "WARN"}),
        patch.object(post_verdict_review, "collect_inline_findings", return_value=[finding]),
        patch.object(
            post_verdict_review,
            "build_patch_index",
            return_value={"src/app.py": ("src/app.py", {9: 2})},
        ),
        patch.object(post_verdict_review, "fetch_comments", return_value=[]),
        patch.object(post_verdict_review, "find_comment_url_by_marker", return_value=""),
        patch.object(post_verdict_review, "create_pr_review", side_effect=error),
        patch.object(post_verdict_review, "warn") as warn_mock,
    ):
        post_verdict_review.main()
    msg = warn_mock.call_args.args[0]
    assert "Review with inline comments failed; skipping PR review." in msg
    # Warning should include the count of inline comments attempted
    assert "1 inline comment" in msg


def test_main_warns_includes_api_response_when_available() -> None:
    """Warning message includes stdout (API response body) for easier debugging."""
    finding = {"severity": "major", "category": "bug", "file": "src/app.py", "line": 9, "title": "t"}
    error = subprocess.CalledProcessError(
        1, ["gh", "api"], stderr="unexpected end of JSON input\n", output='{"message":"Not Found"}'
    )
    with (
        patch.object(post_verdict_review.sys, "argv", _argv("--head-sha", "abcdef123456")),
        patch.object(post_verdict_review, "list_pr_reviews", return_value=[]),
        patch.object(post_verdict_review, "find_review_id_by_marker", return_value=None),
        patch.object(post_verdict_review, "read_json", return_value={"verdict": "WARN"}),
        patch.object(post_verdict_review, "collect_inline_findings", return_value=[finding]),
        patch.object(
            post_verdict_review,
            "build_patch_index",
            return_value={"src/app.py": ("src/app.py", {9: 2})},
        ),
        patch.object(post_verdict_review, "fetch_comments", return_value=[]),
        patch.object(post_verdict_review, "find_comment_url_by_marker", return_value=""),
        patch.object(post_verdict_review, "create_pr_review", side_effect=error),
        patch.object(post_verdict_review, "warn") as warn_mock,
    ):
        post_verdict_review.main()
    msg = warn_mock.call_args.args[0]
    assert "api_response=" in msg
    assert "Not Found" in msg


def test_main_confirms_review_posted_when_gh_parse_fails() -> None:
    """When create_pr_review raises CalledProcessError but the review was actually created
    (gh failed to parse a valid 200 response), detect the posted review and log notice."""
    sha = "abcdef1234567890"
    finding = {
        "severity": "critical",
        "category": "security",
        "file": "src/app.py",
        "line": 12,
        "title": "Critical issue",
        "description": "desc",
        "suggestion": "",
        "evidence": "",
        "reviewers": ["SENTINEL"],
    }
    error = subprocess.CalledProcessError(
        1, ["gh", "api"], stderr="unexpected end of JSON input\n"
    )
    marker = post_verdict_review.review_marker(sha)
    # After the error, the re-check finds the review was actually posted
    review_with_marker = [{"id": 99, "body": marker}]
    with (
        patch.object(post_verdict_review.sys, "argv", _argv("--head-sha", sha)),
        patch.object(
            post_verdict_review,
            "list_pr_reviews",
            side_effect=[[], review_with_marker],
        ),
        patch.object(
            post_verdict_review,
            "find_review_id_by_marker",
            side_effect=[None, 99],
        ),
        patch.object(post_verdict_review, "read_json", return_value={"verdict": "FAIL"}),
        patch.object(post_verdict_review, "collect_inline_findings", return_value=[finding]),
        patch.object(
            post_verdict_review,
            "build_patch_index",
            return_value={"src/app.py": ("src/app.py", {12: 7})},
        ),
        patch.object(post_verdict_review, "fetch_comments", return_value=[]),
        patch.object(post_verdict_review, "find_comment_url_by_marker", return_value=""),
        patch.object(post_verdict_review, "create_pr_review", side_effect=error),
        patch.object(post_verdict_review, "notice") as notice_mock,
        patch.object(post_verdict_review, "warn") as warn_mock,
    ):
        post_verdict_review.main()
    # Review was posted — no warning
    warn_mock.assert_not_called()
    assert any("confirmed" in str(c) for c in notice_mock.call_args_list)


def test_main_warns_on_unexpected_exception() -> None:
    with (
        patch.object(post_verdict_review.sys, "argv", _argv("--head-sha", "abcdef123456")),
        patch.object(post_verdict_review, "list_pr_reviews", side_effect=RuntimeError("boom")),
        patch.object(post_verdict_review, "warn") as warn_mock,
    ):
        post_verdict_review.main()
    assert "Unable to post Cerberus PR review: boom" in warn_mock.call_args.args[0]
