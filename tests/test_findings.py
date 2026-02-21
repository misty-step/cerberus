"""Tests for lib.findings — norm_key, best_text, format_reviewer_list, group_findings."""

from lib.findings import best_text, format_reviewer_list, group_findings, norm_key


class TestNormKey:
    def test_basic_normalization(self):
        assert norm_key("  Hello   World  ") == "hello world"

    def test_none_input(self):
        assert norm_key(None) == ""

    def test_empty_string(self):
        assert norm_key("") == ""

    def test_numeric_input(self):
        assert norm_key(42) == "42"


class TestBestText:
    def test_both_present_picks_longer(self):
        assert best_text("short", "longer text") == "longer text"

    def test_both_present_picks_equal_first(self):
        assert best_text("abc", "xyz") == "abc"

    def test_a_empty(self):
        assert best_text("", "fallback") == "fallback"

    def test_b_empty(self):
        assert best_text("fallback", "") == "fallback"

    def test_both_empty(self):
        assert best_text("", "") == ""

    def test_none_a(self):
        assert best_text(None, "ok") == "ok"

    def test_none_b(self):
        assert best_text("ok", None) == "ok"

    def test_both_none(self):
        assert best_text(None, None) == ""


class TestFormatReviewerList:
    def test_none_returns_unknown(self):
        assert format_reviewer_list(None) == "unknown"

    def test_single_string(self):
        assert format_reviewer_list("APOLLO") == "APOLLO"

    def test_list_of_two(self):
        assert format_reviewer_list(["APOLLO", "ATHENA"]) == "APOLLO, ATHENA"

    def test_list_of_three(self):
        assert format_reviewer_list(["A", "B", "C"]) == "A, B, C"

    def test_list_of_four_truncates(self):
        assert format_reviewer_list(["A", "B", "C", "D"]) == "A, B, +2"

    def test_empty_list_returns_unknown(self):
        assert format_reviewer_list([]) == "unknown"

    def test_list_with_empty_strings_filtered(self):
        assert format_reviewer_list(["", "APOLLO", ""]) == "APOLLO"

    def test_non_iterable_value(self):
        assert format_reviewer_list(42) == "42"

    def test_list_with_none_elements_filtered(self):
        assert format_reviewer_list([None, "APOLLO"]) == "APOLLO"

    def test_all_blank_returns_unknown(self):
        assert format_reviewer_list(["", "  ", ""]) == "unknown"


class TestGroupFindings:
    def _pairs(self, *reviewer_findings: tuple[str, list[dict]]):
        return list(reviewer_findings)

    def test_empty_input_returns_empty(self):
        assert group_findings([]) == []

    def test_single_finding_single_reviewer(self):
        pairs = [("APOLLO", [{"severity": "major", "category": "bug", "file": "a.py", "line": 10, "title": "T"}])]
        out = group_findings(pairs)
        assert len(out) == 1
        assert out[0]["file"] == "a.py"
        assert out[0]["line"] == 10
        assert out[0]["severity"] == "major"
        assert out[0]["category"] == "bug"
        assert out[0]["title"] == "T"
        assert out[0]["reviewers"] == ["APOLLO"]
        assert out[0]["suggestion"] == ""  # default text field

    def test_deduplication_same_key_merges_reviewers(self):
        pairs = [
            ("APOLLO", [{"severity": "major", "category": "Bug", "file": "x.py", "line": 5, "title": "Same Issue"}]),
            ("SENTINEL", [{"severity": "minor", "category": "bug", "file": "x.py", "line": 5, "title": "same issue"}]),
        ]
        out = group_findings(pairs)
        assert len(out) == 1
        assert out[0]["reviewers"] == ["APOLLO", "SENTINEL"]

    def test_worst_severity_wins(self):
        pairs = [
            ("A", [{"severity": "minor", "category": "c", "file": "f.py", "line": 1, "title": "t"}]),
            ("B", [{"severity": "critical", "category": "c", "file": "f.py", "line": 1, "title": "t"}]),
        ]
        out = group_findings(pairs)
        assert out[0]["severity"] == "critical"

    def test_best_text_merges_suggestion(self):
        pairs = [
            ("A", [{"severity": "major", "category": "c", "file": "f.py", "line": 1, "title": "t", "suggestion": "short"}]),
            ("B", [{"severity": "major", "category": "c", "file": "f.py", "line": 1, "title": "t", "suggestion": "much longer suggestion text"}]),
        ]
        out = group_findings(pairs)
        assert out[0]["suggestion"] == "much longer suggestion text"

    def test_multiple_text_fields(self):
        pairs = [
            ("A", [{"severity": "major", "category": "c", "file": "f.py", "line": 1, "title": "t",
                    "description": "short", "evidence": "", "suggestion": "s"}]),
            ("B", [{"severity": "major", "category": "c", "file": "f.py", "line": 1, "title": "t",
                    "description": "longer description here", "evidence": "code snippet", "suggestion": "s"}]),
        ]
        out = group_findings(pairs, text_fields=("description", "suggestion", "evidence"))
        assert out[0]["description"] == "longer description here"
        assert out[0]["evidence"] == "code snippet"

    def test_negative_line_normalized_to_zero(self):
        pairs = [("A", [{"severity": "minor", "category": "c", "file": "f.py", "line": -3, "title": "t"}])]
        out = group_findings(pairs)
        assert out[0]["line"] == 0

    def test_predicate_filters_findings(self):
        pairs = [
            ("A", [
                {"severity": "critical", "category": "c", "file": "keep.py", "line": 1, "title": "t"},
                {"severity": "minor", "category": "c", "file": "skip.py", "line": 1, "title": "t"},
            ])
        ]
        out = group_findings(pairs, predicate=lambda f, _: f.get("file") != "skip.py")
        assert len(out) == 1
        assert out[0]["file"] == "keep.py"

    def test_predicate_receives_reviewer_name(self):
        seen_names: list[str] = []
        def _pred(finding: dict, rname: str) -> bool:
            seen_names.append(rname)
            return True

        pairs = [("Correctness & Logic", [{"severity": "minor", "category": "c", "file": "f.py", "line": 1, "title": "t"}])]
        group_findings(pairs, predicate=_pred)
        assert seen_names == ["Correctness & Logic"]

    def test_reviewers_sorted_alphabetically(self):
        pairs = [
            ("Zebra", [{"severity": "major", "category": "c", "file": "f.py", "line": 1, "title": "t"}]),
            ("Alpha", [{"severity": "major", "category": "c", "file": "f.py", "line": 1, "title": "t"}]),
        ]
        out = group_findings(pairs)
        assert out[0]["reviewers"] == ["Alpha", "Zebra"]

    def test_unknown_severity_defaults_to_info(self):
        pairs = [("A", [{"severity": "bogus", "category": "c", "file": "f.py", "line": 1, "title": "t"}])]
        out = group_findings(pairs)
        assert out[0]["severity"] == "info"

    def test_non_dict_findings_skipped(self):
        pairs = [("A", [None, "bad", {"severity": "major", "category": "c", "file": "f.py", "line": 1, "title": "t"}])]
        out = group_findings(pairs)
        assert len(out) == 1

    def test_distinct_findings_not_merged(self):
        pairs = [
            ("A", [
                {"severity": "major", "category": "c", "file": "f.py", "line": 1, "title": "t1"},
                {"severity": "major", "category": "c", "file": "f.py", "line": 2, "title": "t1"},
            ])
        ]
        out = group_findings(pairs)
        assert len(out) == 2

    def test_custom_severity_order(self):
        # Only two severities in custom order; "major" not in it → treated as least severe
        custom_order = {"critical": 0, "blocker": 1}
        pairs = [
            ("A", [{"severity": "blocker", "category": "c", "file": "f.py", "line": 1, "title": "t"}]),
            ("B", [{"severity": "critical", "category": "c", "file": "f.py", "line": 1, "title": "t"}]),
        ]
        out = group_findings(pairs, severity_order=custom_order)
        assert out[0]["severity"] == "critical"  # 0 beats 1

    def test_non_numeric_line_treated_as_zero(self):
        pairs = [("A", [{"severity": "minor", "category": "c", "file": "f.py", "line": "abc", "title": "t"}])]
        out = group_findings(pairs)
        assert out[0]["line"] == 0

    def test_missing_category_defaults_to_uncategorized(self):
        pairs = [("A", [{"severity": "minor", "file": "f.py", "line": 1, "title": "t"}])]
        out = group_findings(pairs)
        assert out[0]["category"] == "uncategorized"

    def test_missing_title_defaults_to_untitled(self):
        pairs = [("A", [{"severity": "minor", "category": "c", "file": "f.py", "line": 1}])]
        out = group_findings(pairs)
        assert out[0]["title"] == "Untitled finding"

    def test_same_reviewer_duplicate_findings_not_double_counted(self):
        pairs = [("A", [
            {"severity": "major", "category": "c", "file": "f.py", "line": 1, "title": "t"},
            {"severity": "major", "category": "c", "file": "f.py", "line": 1, "title": "t"},
        ])]
        out = group_findings(pairs)
        assert len(out) == 1
        assert out[0]["reviewers"] == ["A"]

    def test_missing_file_field_produces_empty_string(self):
        pairs = [("A", [{"severity": "minor", "category": "c", "line": 1, "title": "t"}])]
        out = group_findings(pairs)
        assert out[0]["file"] == ""


class TestAsInt:
    def test_none(self):
        from lib.findings import as_int
        assert as_int(None) is None

    def test_valid_int(self):
        from lib.findings import as_int
        assert as_int(42) == 42

    def test_string_int(self):
        from lib.findings import as_int
        assert as_int("7") == 7

    def test_invalid(self):
        from lib.findings import as_int
        assert as_int("abc") is None

    def test_float(self):
        from lib.findings import as_int
        assert as_int(3.7) == 3


class TestNormalizeSeverity:
    def test_known(self):
        from lib.findings import normalize_severity
        assert normalize_severity("critical") == "critical"
        assert normalize_severity("MAJOR") == "major"

    def test_unknown_defaults_info(self):
        from lib.findings import normalize_severity
        assert normalize_severity("bad") == "info"
        assert normalize_severity(None) == "info"

    def test_whitespace_collapsed(self):
        from lib.findings import normalize_severity
        assert normalize_severity("  critical  ") == "critical"


class TestSeverityOrder:
    def test_public_severity_order_exists(self):
        from lib.findings import SEVERITY_ORDER
        assert SEVERITY_ORDER == {"critical": 0, "major": 1, "minor": 2, "info": 3}


class TestSplitReviewerDescription:
    def test_em_dash(self):
        from lib.findings import split_reviewer_description
        assert split_reviewer_description("Role — Tagline") == ("Role", "Tagline")

    def test_hyphen(self):
        from lib.findings import split_reviewer_description
        assert split_reviewer_description("Role - Tagline") == ("Role", "Tagline")

    def test_no_separator(self):
        from lib.findings import split_reviewer_description
        assert split_reviewer_description("JustRole") == ("JustRole", "")

    def test_empty(self):
        from lib.findings import split_reviewer_description
        assert split_reviewer_description("") == ("", "")
        assert split_reviewer_description(None) == ("", "")


class TestReviewerLabel:
    def test_uses_role_from_description(self):
        from lib.findings import reviewer_label
        r = {"reviewer_description": "Security — Think like attacker", "perspective": "security", "reviewer": "SENTINEL"}
        assert reviewer_label(r) == "Security"

    def test_falls_back_to_perspective(self):
        from lib.findings import reviewer_label
        r = {"perspective": "security", "reviewer": "SENTINEL"}
        assert reviewer_label(r) == "Security"

    def test_falls_back_to_codename(self):
        from lib.findings import reviewer_label
        r = {"reviewer": "SENTINEL"}
        assert reviewer_label(r) == "Sentinel"

    def test_unknown_perspective_skipped(self):
        from lib.findings import reviewer_label
        r = {"perspective": "unknown", "reviewer": "SENTINEL"}
        assert reviewer_label(r) == "Sentinel"

    def test_empty_returns_unknown(self):
        from lib.findings import reviewer_label
        assert reviewer_label({}) == "unknown"
