"""Tests for lib.findings — norm_key, best_text, format_reviewer_list."""

from lib.findings import best_text, format_reviewer_list, norm_key


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
