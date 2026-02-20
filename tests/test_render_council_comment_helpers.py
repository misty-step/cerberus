"""Branch coverage tests for render_council_comment helper functions.

These test edge-case branches in helper functions that are hard to hit
through the full subprocess rendering pipeline.
"""

import os

from lib.render_council_comment import (
    as_int,
    collect_hotspots,
    collect_issue_groups,
    collect_key_findings,
    count_findings,
    detect_skip_banner,
    finding_location,
    findings_for,
    footer_line,
    format_confidence,
    format_fix_order_lines,
    format_hotspots_lines,
    format_key_findings_lines,
    format_model,
    format_reviewer_details_block,
    format_reviewer_overview_lines,
    format_runtime,
    friendly_codename,
    has_raw_output,
    main,
    normalize_severity,
    normalize_verdict,
    read_json,
    render_comment,
    reviewer_label,
    reviewer_name,
    reviewer_overview_title,
    run_link,
    scope_summary,
    short_model_name,
    short_sha,
    split_reviewer_description,
    summarize_reviewers,
    truncate,
)


class TestAsInt:
    def test_none(self):
        assert as_int(None) is None

    def test_valid_int(self):
        assert as_int(42) == 42

    def test_string_int(self):
        assert as_int("7") == 7

    def test_invalid(self):
        assert as_int("abc") is None

    def test_float(self):
        assert as_int(3.7) == 3


class TestNormalizeVerdict:
    def test_known_verdicts(self):
        assert normalize_verdict("pass") == "PASS"
        assert normalize_verdict("FAIL") == "FAIL"
        assert normalize_verdict("WARN") == "WARN"
        assert normalize_verdict("SKIP") == "SKIP"

    def test_unknown_defaults_warn(self):
        assert normalize_verdict("invalid") == "WARN"
        assert normalize_verdict(None) == "WARN"
        assert normalize_verdict("") == "WARN"


class TestNormalizeSeverity:
    def test_known(self):
        assert normalize_severity("critical") == "critical"
        assert normalize_severity("MAJOR") == "major"

    def test_unknown_defaults_info(self):
        assert normalize_severity("bad") == "info"
        assert normalize_severity(None) == "info"


class TestReviewerName:
    def test_from_reviewer_key(self):
        assert reviewer_name({"reviewer": "APOLLO"}) == "APOLLO"

    def test_from_perspective_key(self):
        assert reviewer_name({"perspective": "security"}) == "security"

    def test_missing_both(self):
        assert reviewer_name({}) == "unknown"


class TestFriendlyCodename:
    def test_allcaps(self):
        assert friendly_codename("APOLLO") == "Apollo"

    def test_mixed_case_unchanged(self):
        assert friendly_codename("Apollo") == "Apollo"

    def test_none(self):
        assert friendly_codename(None) == "unknown"

    def test_empty(self):
        assert friendly_codename("") == "unknown"


class TestSplitReviewerDescription:
    def test_em_dash(self):
        assert split_reviewer_description("Role — Tagline") == ("Role", "Tagline")

    def test_hyphen(self):
        assert split_reviewer_description("Role - Tagline") == ("Role", "Tagline")

    def test_no_separator(self):
        assert split_reviewer_description("JustRole") == ("JustRole", "")

    def test_empty(self):
        assert split_reviewer_description("") == ("", "")
        assert split_reviewer_description(None) == ("", "")


class TestReviewerLabel:
    def test_uses_role_from_description(self):
        r = {"reviewer_description": "Security — Think like attacker", "perspective": "security", "reviewer": "SENTINEL"}
        assert reviewer_label(r) == "Security"

    def test_falls_back_to_perspective(self):
        r = {"perspective": "security", "reviewer": "SENTINEL"}
        assert reviewer_label(r) == "Security"

    def test_falls_back_to_codename(self):
        r = {"reviewer": "SENTINEL"}
        assert reviewer_label(r) == "Sentinel"

    def test_unknown_perspective(self):
        r = {"perspective": "unknown", "reviewer": "SENTINEL"}
        assert reviewer_label(r) == "Sentinel"


class TestReviewerOverviewTitle:
    def test_label_equals_code(self):
        r = {"reviewer": "SENTINEL", "reviewer_description": "Security — Focus", "perspective": "security"}
        # label="Security", code="Sentinel" → differ → shows both
        title = reviewer_overview_title(r)
        assert title == "**Security** (Sentinel)"

    def test_label_matches_code_exact(self):
        r = {"reviewer": "security", "perspective": "unknown"}
        # label falls to friendly_codename("security") = "security", code = "security"
        title = reviewer_overview_title(r)
        assert title == "**security**"

    def test_label_differs_from_code(self):
        r = {"reviewer": "SENTINEL", "reviewer_description": "Security — Focus", "perspective": "security"}
        title = reviewer_overview_title(r)
        assert title == "**Security** (Sentinel)"

    def test_unknown_code(self):
        r = {}
        title = reviewer_overview_title(r)
        assert title == "**unknown**"


class TestFindingsFor:
    def test_valid_list(self):
        assert findings_for({"findings": [{"x": 1}, {"y": 2}]}) == [{"x": 1}, {"y": 2}]

    def test_filters_non_dicts(self):
        assert findings_for({"findings": [{"x": 1}, "bad", 42]}) == [{"x": 1}]

    def test_missing(self):
        assert findings_for({}) == []

    def test_not_list(self):
        assert findings_for({"findings": "bad"}) == []


class TestFormatRuntime:
    def test_seconds(self):
        assert format_runtime(45) == "45s"

    def test_minutes(self):
        assert format_runtime(65) == "1m 5s"

    def test_negative(self):
        assert format_runtime(-1) == "n/a"

    def test_none(self):
        assert format_runtime(None) == "n/a"

    def test_zero(self):
        assert format_runtime(0) == "0s"


class TestShortModelName:
    def test_openrouter_prefix(self):
        assert short_model_name("openrouter/moonshotai/kimi-k2.5") == "kimi-k2.5"

    def test_no_prefix(self):
        assert short_model_name("kimi-k2.5") == "kimi-k2.5"

    def test_single_slash(self):
        assert short_model_name("provider/model") == "model"


class TestFormatModel:
    def test_normal(self):
        assert format_model({"model_used": "openrouter/moonshotai/kimi-k2.5"}) == "`kimi-k2.5`"

    def test_fallback(self):
        r = {"model_used": "openrouter/deepseek/v3", "primary_model": "openrouter/kimi/k2.5", "fallback_used": True}
        result = format_model(r)
        assert "fallback from" in result
        assert "`v3`" in result

    def test_no_model(self):
        assert format_model({}) is None
        assert format_model({"model_used": ""}) is None
        assert format_model({"model_used": 42}) is None

    def test_fallback_no_primary(self):
        r = {"model_used": "openrouter/deepseek/v3", "fallback_used": True}
        result = format_model(r)
        assert result == "`v3`"


class TestFormatConfidence:
    def test_normal(self):
        assert format_confidence(0.85) == "0.85"

    def test_none(self):
        assert format_confidence(None) == "n/a"

    def test_invalid(self):
        assert format_confidence("bad") == "n/a"

    def test_out_of_range_high(self):
        assert format_confidence(1.5) == "n/a"

    def test_out_of_range_low(self):
        assert format_confidence(-0.1) == "n/a"

    def test_boundary(self):
        assert format_confidence(0) == "0.00"
        assert format_confidence(1) == "1.00"


class TestSummarizeReviewers:
    def test_empty(self):
        assert summarize_reviewers([]) == "No reviewer verdicts available."

    def test_all_pass(self):
        reviewers = [
            {"verdict": "PASS", "perspective": "a"},
            {"verdict": "PASS", "perspective": "b"},
        ]
        result = summarize_reviewers(reviewers)
        assert "2/2 reviewers passed" in result

    def test_mixed(self):
        reviewers = [
            {"verdict": "PASS", "perspective": "a"},
            {"verdict": "FAIL", "perspective": "b"},
            {"verdict": "WARN", "perspective": "c"},
            {"verdict": "SKIP", "perspective": "d"},
        ]
        result = summarize_reviewers(reviewers)
        assert "1/4 reviewers passed" in result
        assert "1 failed" in result
        assert "1 warned" in result
        assert "1 skipped" in result


class TestFindingLocation:
    def test_file_and_line(self):
        assert finding_location({"file": "a.py", "line": 10}) == "a.py:10"

    def test_file_only(self):
        assert finding_location({"file": "a.py"}) == "a.py"

    def test_no_file(self):
        assert finding_location({}) == "location n/a"

    def test_line_zero(self):
        assert finding_location({"file": "a.py", "line": 0}) == "a.py"


class TestTruncate:
    def test_short(self):
        assert truncate("hello", max_len=10) == "hello"

    def test_long(self):
        assert truncate("hello world", max_len=8) == "hello w…"

    def test_none(self):
        assert truncate(None, max_len=10) == ""


class TestCountFindings:
    def test_uses_stats(self):
        reviewers = [{"stats": {"critical": 2, "major": 1, "minor": 0, "info": 3}}]
        totals = count_findings(reviewers)
        assert totals["critical"] == 2

    def test_falls_back_to_findings(self):
        reviewers = [
            {"findings": [{"severity": "critical"}, {"severity": "major"}]},
        ]
        totals = count_findings(reviewers)
        assert totals["critical"] == 1
        assert totals["major"] == 1

    def test_no_stats_no_findings(self):
        totals = count_findings([{}])
        assert totals == {"critical": 0, "major": 0, "minor": 0, "info": 0}

    def test_partial_stats_uses_stats(self):
        reviewers = [{"stats": {"critical": 1}, "findings": [{"severity": "major"}]}]
        totals = count_findings(reviewers)
        assert totals["critical"] == 1
        assert totals["major"] == 0  # stats branch was used, not findings

    def test_stats_dict_with_no_matching_keys_falls_back(self):
        """When stats is a dict but has no recognized severity keys, fall through to findings."""
        reviewers = [{"stats": {"other": 99}, "findings": [{"severity": "minor"}]}]
        totals = count_findings(reviewers)
        assert totals["minor"] == 1  # fell back to counting findings


class TestDetectSkipBanner:
    def test_credit_depleted(self):
        r = [{"verdict": "SKIP", "summary": "err", "findings": [{"category": "api_error", "title": "CREDITS_DEPLETED"}]}]
        assert "credits depleted" in detect_skip_banner(r)

    def test_quota_exceeded(self):
        r = [{"verdict": "SKIP", "summary": "err", "findings": [{"category": "api_error", "title": "QUOTA_EXCEEDED"}]}]
        assert "credits depleted" in detect_skip_banner(r)

    def test_key_invalid(self):
        r = [{"verdict": "SKIP", "summary": "err", "findings": [{"category": "api_error", "title": "KEY_INVALID"}]}]
        assert "API key error" in detect_skip_banner(r)

    def test_generic_api_error(self):
        r = [{"verdict": "SKIP", "summary": "err", "findings": [{"category": "api_error", "title": "RATE_LIMITED"}]}]
        assert "API error" in detect_skip_banner(r)

    def test_timeout_category(self):
        r = [{"verdict": "SKIP", "summary": "review timed out", "findings": [{"category": "timeout", "title": "TIMEOUT"}]}]
        assert "timed out" in detect_skip_banner(r)

    def test_timeout_in_summary(self):
        r = [{"verdict": "SKIP", "summary": "timeout occurred", "findings": [{"category": "other", "title": "X"}]}]
        assert "timed out" in detect_skip_banner(r)

    def test_no_skip_reviewers(self):
        assert detect_skip_banner([{"verdict": "PASS"}]) == ""

    def test_skip_no_findings(self):
        r = [{"verdict": "SKIP", "summary": "ok", "findings": []}]
        assert detect_skip_banner(r) == ""


class TestScopeSummary:
    def test_with_env(self, monkeypatch):
        monkeypatch.setenv("PR_CHANGED_FILES", "5")
        monkeypatch.setenv("PR_ADDITIONS", "100")
        monkeypatch.setenv("PR_DELETIONS", "20")
        assert scope_summary() == "5 files changed, +100 / -20 lines"

    def test_missing_env(self, monkeypatch):
        monkeypatch.delenv("PR_CHANGED_FILES", raising=False)
        monkeypatch.delenv("PR_ADDITIONS", raising=False)
        monkeypatch.delenv("PR_DELETIONS", raising=False)
        assert "unknown scope" in scope_summary()


class TestRunLink:
    def test_with_env(self, monkeypatch):
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("GITHUB_RUN_ID", "12345")
        label, url = run_link()
        assert label == "#12345"
        assert "actions/runs/12345" in url

    def test_missing_env(self, monkeypatch):
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
        label, url = run_link()
        assert label == "n/a"
        assert url == ""


class TestShortSha:
    def test_with_env(self, monkeypatch):
        monkeypatch.setenv("GH_HEAD_SHA", "abcdef1234567890deadbeef")
        assert short_sha() == "abcdef123456"

    def test_missing(self, monkeypatch):
        monkeypatch.delenv("GH_HEAD_SHA", raising=False)
        assert short_sha() == "<head-sha>"


class TestFooterLine:
    def test_contains_version_and_override(self, monkeypatch):
        monkeypatch.setenv("CERBERUS_VERSION", "v2.1")
        monkeypatch.setenv("GH_OVERRIDE_POLICY", "pr_author")
        monkeypatch.setenv("FAIL_ON_VERDICT", "true")
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("GITHUB_RUN_ID", "999")
        monkeypatch.setenv("GH_HEAD_SHA", "abc123")
        line = footer_line()
        assert "v2.1" in line
        assert "pr_author" in line
        assert "/council override sha=" in line

    def test_no_run_url(self, monkeypatch):
        monkeypatch.setenv("CERBERUS_VERSION", "dev")
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
        monkeypatch.setenv("GH_OVERRIDE_POLICY", "pr_author")
        monkeypatch.setenv("FAIL_ON_VERDICT", "true")
        monkeypatch.setenv("GH_HEAD_SHA", "abc")
        line = footer_line()
        assert "n/a" in line


class TestHasRawOutput:
    def test_true(self):
        assert has_raw_output([{"raw_review": "some text"}]) is True

    def test_false_empty(self):
        assert has_raw_output([{"raw_review": ""}]) is False

    def test_false_missing(self):
        assert has_raw_output([{}]) is False

    def test_false_non_string(self):
        assert has_raw_output([{"raw_review": 42}]) is False


class TestFormatReviewerOverviewLines:
    def test_empty(self):
        assert format_reviewer_overview_lines([]) == ["- No reviewer verdicts available."]

    def test_single_reviewer(self):
        r = [{"reviewer": "APOLLO", "perspective": "correctness", "verdict": "PASS",
              "confidence": 0.9, "runtime_seconds": 10, "findings": []}]
        lines = format_reviewer_overview_lines(r)
        assert len(lines) == 1
        assert "PASS" in lines[0]


class TestFormatFixOrderLines:
    def test_no_findings(self):
        assert format_fix_order_lines([], max_items=3) == ["_No findings reported._"]

    def test_finding_with_zero_line(self, monkeypatch):
        """line <= 0 should be normalized to None (no line anchor)."""
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://gh.com")
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("GH_HEAD_SHA", "abc")
        reviewers = [{"reviewer": "A", "findings": [
            {"severity": "minor", "category": "style", "file": "a.py",
             "line": 0, "title": "Nit"},
        ]}]
        lines = format_fix_order_lines(reviewers, max_items=5)
        text = "\n".join(lines)
        assert "a.py`]" in text
        assert "#L0" not in text  # line=0 should not produce an anchor

    def test_finding_without_suggestion(self, monkeypatch):
        """No suggestion → no 'Fix:' line emitted."""
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://gh.com")
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("GH_HEAD_SHA", "abc")
        reviewers = [{"reviewer": "A", "findings": [
            {"severity": "minor", "category": "c", "file": "b.py",
             "line": 1, "title": "Test"},
        ]}]
        lines = format_fix_order_lines(reviewers, max_items=5)
        assert not any("Fix:" in ln for ln in lines)


class TestFormatHotspotsLines:
    def test_no_hotspots(self, monkeypatch):
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://gh.com")
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("GH_HEAD_SHA", "abc")
        assert format_hotspots_lines([], max_files=5) == ["_No hotspots detected._"]


class TestFormatKeyFindingsLines:
    def test_no_findings(self):
        assert format_key_findings_lines([], max_total=10) == ["_No findings reported._"]


class TestFormatReviewerDetailsBlock:
    def test_reviewer_code_matches_label(self, monkeypatch):
        """When codename == label, header should not duplicate (no 'X (X)')."""
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://gh.com")
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("GH_HEAD_SHA", "abc")
        r = [{
            "reviewer": "Custom",
            "perspective": "custom",
            "verdict": "PASS",
            "confidence": 0.9,
            "runtime_seconds": 5,
            "summary": "ok",
            "findings": [],
        }]
        lines = format_reviewer_details_block(r, max_findings=5)
        text = "\n".join(lines)
        assert "Custom (Custom)" not in text  # should not duplicate

    def test_reviewer_with_findings(self, monkeypatch):
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://gh.com")
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("GH_HEAD_SHA", "abc")
        r = [{
            "reviewer": "SENTINEL",
            "perspective": "security",
            "reviewer_description": "Security — Threat model",
            "verdict": "WARN",
            "confidence": 0.8,
            "runtime_seconds": 30,
            "summary": "Found issues",
            "model_used": "openrouter/kimi/k2.5",
            "findings": [
                {"severity": "major", "category": "auth", "file": "a.py", "line": 1,
                 "title": "Auth issue", "description": "Bad auth", "suggestion": "Fix auth"},
            ],
        }]
        lines = format_reviewer_details_block(r, max_findings=5)
        text = "\n".join(lines)
        assert "Security (Sentinel)" in text
        assert "Threat model" in text
        assert "Auth issue" in text
        assert "Model:" in text

    def test_reviewer_no_findings(self, monkeypatch):
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://gh.com")
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("GH_HEAD_SHA", "abc")
        r = [{"reviewer": "APOLLO", "perspective": "correctness", "verdict": "PASS",
              "confidence": 0.9, "runtime_seconds": 10, "summary": "ok", "findings": []}]
        lines = format_reviewer_details_block(r, max_findings=5)
        text = "\n".join(lines)
        assert "No findings reported" in text

    def test_hidden_findings_count(self, monkeypatch):
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://gh.com")
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("GH_HEAD_SHA", "abc")
        r = [{
            "reviewer": "A",
            "perspective": "x",
            "verdict": "WARN",
            "confidence": 0.5,
            "runtime_seconds": 5,
            "summary": "many",
            "findings": [
                {"severity": "minor", "category": "c", "file": f"f{i}.py", "line": i, "title": f"F{i}"}
                for i in range(5)
            ],
        }]
        lines = format_reviewer_details_block(r, max_findings=2)
        text = "\n".join(lines)
        assert "Additional findings not shown: 3" in text


class TestCollectIssueGroups:
    def test_na_files_filtered(self):
        r = [{"reviewer": "A", "findings": [
            {"file": "N/A", "line": 0, "severity": "minor", "category": "x", "title": "t"},
        ]}]
        assert collect_issue_groups(r) == []

    def test_negative_line_normalized(self):
        r = [{"reviewer": "A", "findings": [
            {"file": "a.py", "line": -5, "severity": "minor", "category": "x", "title": "t"},
        ]}]
        groups = collect_issue_groups(r)
        assert groups[0]["line"] == 0


class TestRenderCommentIntegration:
    def test_pass_verdict_minimal(self, monkeypatch):
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://gh.com")
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("GITHUB_RUN_ID", "1")
        monkeypatch.setenv("GH_HEAD_SHA", "abc")
        monkeypatch.setenv("PR_CHANGED_FILES", "1")
        monkeypatch.setenv("PR_ADDITIONS", "10")
        monkeypatch.setenv("PR_DELETIONS", "5")
        monkeypatch.setenv("CERBERUS_VERSION", "v2")
        monkeypatch.setenv("GH_OVERRIDE_POLICY", "pr_author")
        monkeypatch.setenv("FAIL_ON_VERDICT", "true")

        comment = render_comment(
            {"verdict": "PASS", "reviewers": [
                {"reviewer": "A", "perspective": "x", "verdict": "PASS",
                 "confidence": 0.9, "summary": "ok", "findings": [],
                 "stats": {"critical": 0, "major": 0, "minor": 0, "info": 0}},
            ]},
            max_findings=5,
            max_key_findings=5,
            marker="<!-- test -->",
        )
        assert "PASS" in comment
        assert "Reviewer details" not in comment  # no details for all-pass

    def test_warn_verdict_with_findings(self, monkeypatch):
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://gh.com")
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("GITHUB_RUN_ID", "1")
        monkeypatch.setenv("GH_HEAD_SHA", "abc")
        monkeypatch.setenv("PR_CHANGED_FILES", "1")
        monkeypatch.setenv("PR_ADDITIONS", "10")
        monkeypatch.setenv("PR_DELETIONS", "5")
        monkeypatch.setenv("CERBERUS_VERSION", "v2")
        monkeypatch.setenv("GH_OVERRIDE_POLICY", "pr_author")
        monkeypatch.setenv("FAIL_ON_VERDICT", "true")

        comment = render_comment(
            {"verdict": "WARN", "reviewers": [
                {"reviewer": "A", "perspective": "x", "verdict": "WARN",
                 "confidence": 0.7, "summary": "issue",
                 "findings": [{"severity": "major", "category": "bug", "file": "a.py",
                                "line": 1, "title": "Bug", "description": "d", "suggestion": "s"}],
                 "stats": {"critical": 0, "major": 1, "minor": 0, "info": 0}},
            ]},
            max_findings=5,
            max_key_findings=5,
            marker="<!-- test -->",
        )
        assert "WARN" in comment
        assert "Fix Order" in comment
        assert "Hotspots" in comment
        assert "Key Findings" in comment
        assert "show less" in comment  # expanded details for WARN

    def test_pass_verdict_key_findings_collapsed(self, monkeypatch):
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://gh.com")
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("GITHUB_RUN_ID", "1")
        monkeypatch.setenv("GH_HEAD_SHA", "abc")
        monkeypatch.setenv("PR_CHANGED_FILES", "1")
        monkeypatch.setenv("PR_ADDITIONS", "10")
        monkeypatch.setenv("PR_DELETIONS", "5")
        monkeypatch.setenv("CERBERUS_VERSION", "v2")
        monkeypatch.setenv("GH_OVERRIDE_POLICY", "pr_author")
        monkeypatch.setenv("FAIL_ON_VERDICT", "true")

        comment = render_comment(
            {"verdict": "PASS", "reviewers": [
                {"reviewer": "A", "perspective": "x", "verdict": "PASS",
                 "confidence": 0.9, "summary": "ok",
                 "findings": [{"severity": "info", "category": "style", "file": "a.py",
                                "line": 1, "title": "Nit"}],
                 "stats": {"critical": 0, "major": 0, "minor": 0, "info": 1}},
            ]},
            max_findings=5,
            max_key_findings=5,
            marker="<!-- test -->",
        )
        assert "Key Findings" in comment
        assert "click to expand" in comment  # collapsed for PASS

    def test_non_list_reviewers_handled(self, monkeypatch):
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://gh.com")
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("GITHUB_RUN_ID", "1")
        monkeypatch.setenv("GH_HEAD_SHA", "abc")
        monkeypatch.setenv("PR_CHANGED_FILES", "1")
        monkeypatch.setenv("PR_ADDITIONS", "10")
        monkeypatch.setenv("PR_DELETIONS", "5")
        monkeypatch.setenv("CERBERUS_VERSION", "v2")
        monkeypatch.setenv("GH_OVERRIDE_POLICY", "pr_author")
        monkeypatch.setenv("FAIL_ON_VERDICT", "true")

        comment = render_comment(
            {"verdict": "PASS", "reviewers": "not a list"},
            max_findings=5,
            max_key_findings=5,
            marker="<!-- test -->",
        )
        assert "No reviewer verdicts available" in comment

    def test_stats_missing_recalculates(self, monkeypatch):
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://gh.com")
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("GITHUB_RUN_ID", "1")
        monkeypatch.setenv("GH_HEAD_SHA", "abc")
        monkeypatch.setenv("PR_CHANGED_FILES", "1")
        monkeypatch.setenv("PR_ADDITIONS", "10")
        monkeypatch.setenv("PR_DELETIONS", "5")
        monkeypatch.setenv("CERBERUS_VERSION", "v2")
        monkeypatch.setenv("GH_OVERRIDE_POLICY", "pr_author")
        monkeypatch.setenv("FAIL_ON_VERDICT", "true")

        comment = render_comment(
            {"verdict": "PASS", "reviewers": [
                {"reviewer": "A", "verdict": "PASS", "confidence": 0.9,
                 "summary": "ok", "findings": []},
            ]},
            max_findings=5,
            max_key_findings=5,
            marker="<!-- test -->",
        )
        assert "1 total | 1 pass" in comment


class TestReadJson:
    def test_valid(self, tmp_path):
        p = tmp_path / "test.json"
        p.write_text('{"key": "value"}')
        assert read_json(p) == {"key": "value"}

    def test_invalid_json(self, tmp_path):
        import pytest
        p = tmp_path / "test.json"
        p.write_text("not json")
        with pytest.raises(ValueError, match="invalid JSON"):
            read_json(p)

    def test_missing_file(self, tmp_path):
        import pytest
        p = tmp_path / "missing.json"
        with pytest.raises(IOError, match="unable to read"):
            read_json(p)

    def test_non_object(self, tmp_path):
        import pytest
        p = tmp_path / "test.json"
        p.write_text("[1, 2, 3]")
        with pytest.raises(ValueError, match="expected object"):
            read_json(p)


class TestMainErrorPaths:
    def test_max_key_findings_zero(self, tmp_path, capsys):
        council_path = tmp_path / "council.json"
        council_path.write_text('{"verdict":"PASS","reviewers":[]}')
        code = main([
            "--council-json", str(council_path),
            "--output", str(tmp_path / "out.md"),
            "--max-key-findings", "0",
        ])
        assert code == 2
        captured = capsys.readouterr()
        assert "max-key-findings" in captured.err

    def test_write_failure(self, tmp_path, capsys):
        council_path = tmp_path / "council.json"
        council_path.write_text('{"verdict":"PASS","reviewers":[]}')
        code = main([
            "--council-json", str(council_path),
            "--output", str(tmp_path / "no" / "such" / "dir" / "out.md"),
        ])
        assert code == 2
        captured = capsys.readouterr()
        assert "unable to write" in captured.err
