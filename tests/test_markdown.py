"""Tests for lib.markdown — severity_icon, repo_context, blob_url, location_link, details_block."""

import os

from lib.markdown import blob_url, details_block, location_link, repo_context, severity_icon


class TestSeverityIcon:
    def test_known_severities(self):
        assert severity_icon("critical") == "🔴"
        assert severity_icon("major") == "🟠"
        assert severity_icon("minor") == "🟡"
        assert severity_icon("info") == "🔵"

    def test_case_insensitive(self):
        assert severity_icon("CRITICAL") == "🔴"
        assert severity_icon("  Major  ") == "🟠"

    def test_unknown_defaults_to_info(self):
        assert severity_icon("unknown") == "🔵"
        assert severity_icon(None) == "🔵"
        assert severity_icon("") == "🔵"


class TestRepoContext:
    def test_explicit_params(self):
        server, repo, sha = repo_context(
            server="https://example.com",
            repo="org/repo",
            sha="abc123",
        )
        assert server == "https://example.com"
        assert repo == "org/repo"
        assert sha == "abc123"

    def test_strips_trailing_slash(self):
        server, _, _ = repo_context(server="https://example.com/")
        assert server == "https://example.com"

    def test_env_fallback(self, monkeypatch):
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://gh.test")
        monkeypatch.setenv("GITHUB_REPOSITORY", "test/repo")
        monkeypatch.setenv("GH_HEAD_SHA", "deadbeef")
        server, repo, sha = repo_context()
        assert server == "https://gh.test"
        assert repo == "test/repo"
        assert sha == "deadbeef"

    def test_defaults_when_no_env(self, monkeypatch):
        monkeypatch.delenv("GITHUB_SERVER_URL", raising=False)
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        monkeypatch.delenv("GH_HEAD_SHA", raising=False)
        server, repo, sha = repo_context()
        assert server == "https://github.com"
        assert repo == ""
        assert sha == ""


class TestBlobUrl:
    def test_full_url_with_line(self):
        url = blob_url(
            "src/app.py",
            server="https://github.com",
            repo="org/repo",
            sha="abc",
            line=42,
        )
        assert url == "https://github.com/org/repo/blob/abc/src/app.py#L42"

    def test_url_without_line(self):
        url = blob_url(
            "src/app.py",
            server="https://github.com",
            repo="org/repo",
            sha="abc",
        )
        assert url == "https://github.com/org/repo/blob/abc/src/app.py"

    def test_line_zero_no_fragment(self):
        url = blob_url(
            "src/app.py",
            server="https://github.com",
            repo="org/repo",
            sha="abc",
            line=0,
        )
        assert url == "https://github.com/org/repo/blob/abc/src/app.py"

    def test_missing_server_returns_none(self):
        assert blob_url("f.py", server="", repo="org/repo", sha="abc") is None

    def test_missing_repo_returns_none(self):
        assert blob_url("f.py", server="https://gh.com", repo="", sha="abc") is None

    def test_missing_sha_returns_none(self):
        assert blob_url("f.py", server="https://gh.com", repo="org/r", sha="") is None

    def test_missing_path_returns_none(self):
        assert blob_url("", server="https://gh.com", repo="org/r", sha="abc") is None

    def test_none_path_returns_none(self):
        assert blob_url(None, server="https://gh.com", repo="org/r", sha="abc") is None

    def test_negative_line_no_fragment(self):
        url = blob_url(
            "f.py",
            server="https://github.com",
            repo="org/repo",
            sha="abc",
            line=-1,
        )
        assert url == "https://github.com/org/repo/blob/abc/f.py"


class TestLocationLink:
    def test_full_link(self):
        result = location_link(
            "src/app.py",
            42,
            server="https://github.com",
            repo="org/repo",
            sha="abc",
        )
        assert "[`src/app.py:42`]" in result
        assert "https://github.com/org/repo/blob/abc/src/app.py#L42" in result

    def test_empty_path_returns_missing_label(self):
        result = location_link("", None, server="s", repo="r", sha="a")
        assert result == "`unknown`"

    def test_custom_missing_label(self):
        result = location_link(
            "", None, server="s", repo="r", sha="a", missing_label="n/a"
        )
        assert result == "`n/a`"

    def test_na_path_returns_backtick_na(self):
        result = location_link(
            "N/A", None, server="https://gh.com", repo="org/r", sha="abc"
        )
        assert result == "`N/A`"

    def test_no_blob_url_returns_backtick_label(self):
        result = location_link("src/app.py", 10, server="", repo="", sha="")
        assert result == "`src/app.py:10`"

    def test_path_without_line(self):
        result = location_link(
            "src/app.py",
            None,
            server="https://github.com",
            repo="org/repo",
            sha="abc",
        )
        assert "[`src/app.py`]" in result


class TestDetailsBlock:
    def test_empty_body_returns_empty(self):
        assert details_block([]) == []

    def test_single_line(self):
        result = details_block(["hello"])
        assert "<details>" in result[0]
        assert "<summary>Details</summary>" in result[1]
        assert any("hello" in line for line in result)
        assert "</details>" in result[-1]

    def test_empty_line_in_body(self):
        result = details_block(["hello", "", "world"])
        assert "" in result  # empty lines preserved

    def test_custom_summary_and_indent(self):
        result = details_block(["x"], summary="More", indent="    ")
        assert result[0] == "    <details>"
        assert "    <summary>More</summary>" in result[1]
