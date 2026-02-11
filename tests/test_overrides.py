"""Tests for scripts/lib/overrides.py — override parsing and authorization."""
import json
import sys
from pathlib import Path

import pytest

# Import the module directly (it's a proper package now).
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from lib.overrides import (
    Override,
    POLICY_STRICTNESS,
    determine_effective_policy,
    parse_override,
    select_override,
    validate_actor,
)


def _verdict(name: str, result: str = "PASS", **extra) -> dict:
    return {"reviewer": name, "perspective": name.lower(), "verdict": result, "summary": "ok", **extra}


# ---------------------------------------------------------------------------
# Override dataclass
# ---------------------------------------------------------------------------

class TestOverrideDataclass:
    def test_creation(self):
        o = Override(actor="user", sha="abc1234", reason="verified")
        assert o.actor == "user"
        assert o.sha == "abc1234"
        assert o.reason == "verified"

    def test_frozen(self):
        o = Override(actor="user", sha="abc1234", reason="verified")
        with pytest.raises(AttributeError):
            o.actor = "other"

    def test_equality(self):
        a = Override(actor="user", sha="abc1234", reason="verified")
        b = Override(actor="user", sha="abc1234", reason="verified")
        assert a == b

    def test_dict_conversion(self):
        """Override should be convertible to dict for JSON serialization."""
        from dataclasses import asdict
        o = Override(actor="user", sha="abc1234", reason="verified")
        d = asdict(o)
        assert d == {"actor": "user", "sha": "abc1234", "reason": "verified"}


# ---------------------------------------------------------------------------
# parse_override
# ---------------------------------------------------------------------------

class TestParseOverride:
    def test_none_input(self):
        assert parse_override(None, "abc1234") is None

    def test_empty_string(self):
        assert parse_override("", "abc1234") is None

    def test_null_string(self):
        assert parse_override("null", "abc1234") is None

    def test_none_string(self):
        assert parse_override("None", "abc1234") is None

    def test_whitespace_only(self):
        assert parse_override("   ", "abc1234") is None

    def test_invalid_json(self):
        assert parse_override("{not json}", "abc1234") is None

    def test_missing_sha(self):
        raw = json.dumps({"actor": "user", "reason": "good reason"})
        assert parse_override(raw, "abc1234") is None

    def test_missing_reason(self):
        raw = json.dumps({"actor": "user", "sha": "abc1234"})
        assert parse_override(raw, "abc1234") is None

    def test_sha_too_short(self):
        raw = json.dumps({"actor": "user", "sha": "abc", "reason": "ok"})
        assert parse_override(raw, "abc1234") is None

    def test_sha_mismatch(self):
        raw = json.dumps({"actor": "user", "sha": "def7890", "reason": "ok"})
        assert parse_override(raw, "abc1234") is None

    def test_valid_override(self):
        raw = json.dumps({"actor": "user", "sha": "abc1234", "reason": "verified"})
        result = parse_override(raw, "abc1234567890")
        assert result == Override(actor="user", sha="abc1234", reason="verified")

    def test_returns_override_instance(self):
        raw = json.dumps({"actor": "user", "sha": "abc1234", "reason": "verified"})
        result = parse_override(raw, "abc1234")
        assert isinstance(result, Override)

    def test_no_head_sha_skips_check(self):
        raw = json.dumps({"actor": "user", "sha": "abc1234", "reason": "ok"})
        result = parse_override(raw, None)
        assert result is not None
        assert result.sha == "abc1234"

    def test_body_parsing_extracts_sha_and_reason(self):
        raw = json.dumps({
            "actor": "user",
            "body": "/council override sha=abc1234\nReason: False positive confirmed",
        })
        result = parse_override(raw, "abc1234567890")
        assert result is not None
        assert result.sha == "abc1234"
        assert result.reason == "False positive confirmed"

    def test_body_parsing_remainder_as_reason(self):
        raw = json.dumps({
            "actor": "user",
            "body": "/council override sha=abc1234\nThis is a false positive and safe to merge",
        })
        result = parse_override(raw, "abc1234567890")
        assert result is not None
        assert result.reason == "This is a false positive and safe to merge"

    def test_body_sha_does_not_override_explicit_sha(self):
        raw = json.dumps({
            "actor": "user",
            "sha": "explicit1",
            "body": "/council override sha=body1234\nReason: test",
        })
        result = parse_override(raw, "explicit1234567890")
        assert result is not None
        assert result.sha == "explicit1"

    def test_author_field_fallback(self):
        raw = json.dumps({"author": "alt-user", "sha": "abc1234", "reason": "ok"})
        result = parse_override(raw, "abc1234")
        assert result.actor == "alt-user"

    def test_actor_defaults_to_unknown(self):
        raw = json.dumps({"sha": "abc1234", "reason": "ok"})
        result = parse_override(raw, "abc1234")
        assert result.actor == "unknown"

    def test_extra_whitespace_in_body(self):
        raw = json.dumps({
            "actor": "user",
            "body": "  /council override sha=abc1234  \n  Reason:  spaced out  ",
        })
        result = parse_override(raw, "abc1234567890")
        assert result is not None
        assert result.reason == "spaced out"

    def test_mixed_case_reason_prefix(self):
        raw = json.dumps({
            "actor": "user",
            "body": "/council override sha=abc1234\nREASON: uppercase reason",
        })
        result = parse_override(raw, "abc1234567890")
        assert result is not None
        assert result.reason == "uppercase reason"


# ---------------------------------------------------------------------------
# validate_actor
# ---------------------------------------------------------------------------

class TestValidateActor:
    def test_pr_author_match(self):
        assert validate_actor("user", "pr_author", "user") is True

    def test_pr_author_case_insensitive(self):
        assert validate_actor("User", "pr_author", "user") is True

    def test_pr_author_mismatch(self):
        assert validate_actor("other", "pr_author", "user") is False

    def test_pr_author_none(self):
        assert validate_actor("user", "pr_author", None) is False

    def test_write_access_write(self):
        assert validate_actor("user", "write_access", "other", "write") is True

    def test_write_access_maintain(self):
        assert validate_actor("user", "write_access", "other", "maintain") is True

    def test_write_access_admin(self):
        assert validate_actor("user", "write_access", "other", "admin") is True

    def test_write_access_read(self):
        assert validate_actor("user", "write_access", "other", "read") is False

    def test_write_access_none(self):
        assert validate_actor("user", "write_access", "other", None) is False

    def test_maintainers_only_admin(self):
        assert validate_actor("user", "maintainers_only", "other", "admin") is True

    def test_maintainers_only_maintain(self):
        assert validate_actor("user", "maintainers_only", "other", "maintain") is True

    def test_maintainers_only_write(self):
        assert validate_actor("user", "maintainers_only", "other", "write") is False

    def test_maintainers_only_read(self):
        assert validate_actor("user", "maintainers_only", "other", "read") is False

    def test_unknown_policy_rejects(self):
        assert validate_actor("user", "unknown", "user") is False


# ---------------------------------------------------------------------------
# select_override
# ---------------------------------------------------------------------------

class TestSelectOverride:
    def test_single_authorized(self):
        comments = json.dumps([
            {"actor": "author", "sha": "abc1234", "reason": "verified"},
        ])
        result = select_override(comments, "abc1234", "pr_author", "author")
        assert result is not None
        assert result.actor == "author"
        assert isinstance(result, Override)

    def test_first_authorized_from_multiple(self):
        comments = json.dumps([
            {"actor": "author", "sha": "abc1234", "reason": "first override"},
            {"actor": "author", "sha": "abc1234", "reason": "second override"},
        ])
        result = select_override(comments, "abc1234", "pr_author", "author")
        assert result is not None
        assert result.reason == "first override"

    def test_unauthorized_skipped(self):
        comments = json.dumps([
            {"actor": "intruder", "sha": "abc1234", "reason": "sneaky"},
            {"actor": "author", "sha": "abc1234", "reason": "legit"},
        ])
        result = select_override(comments, "abc1234", "pr_author", "author")
        assert result is not None
        assert result.actor == "author"
        assert result.reason == "legit"

    def test_no_authorized_returns_none(self):
        comments = json.dumps([
            {"actor": "intruder1", "sha": "abc1234", "reason": "nope"},
            {"actor": "intruder2", "sha": "abc1234", "reason": "also nope"},
        ])
        result = select_override(comments, "abc1234", "pr_author", "author")
        assert result is None

    def test_none_input(self):
        assert select_override(None, "abc1234", "pr_author", "author") is None

    def test_empty_array(self):
        assert select_override("[]", "abc1234", "pr_author", "author") is None

    def test_invalid_json(self):
        assert select_override("{bad", "abc1234", "pr_author", "author") is None

    def test_single_object_backward_compat(self):
        comment = json.dumps(
            {"actor": "author", "sha": "abc1234", "reason": "verified"},
        )
        result = select_override(comment, "abc1234", "pr_author", "author")
        assert result is not None
        assert result.actor == "author"

    def test_write_access_with_permissions(self):
        comments = json.dumps([
            {"actor": "reader", "sha": "abc1234", "reason": "no perms"},
            {"actor": "admin", "sha": "abc1234", "reason": "has perms"},
        ])
        result = select_override(
            comments, "abc1234", "write_access", "other",
            actor_permissions={"reader": "read", "admin": "admin"},
        )
        assert result is not None
        assert result.actor == "admin"

    def test_sha_mismatch_skipped(self):
        comments = json.dumps([
            {"actor": "author", "sha": "wrongsha", "reason": "bad sha"},
            {"actor": "author", "sha": "abc1234", "reason": "right sha"},
        ])
        result = select_override(comments, "abc1234", "pr_author", "author")
        assert result is not None
        assert result.reason == "right sha"

    def test_logs_selection_reason(self, capsys):
        comments = json.dumps([
            {"actor": "intruder", "sha": "abc1234", "reason": "bad"},
            {"actor": "author", "sha": "abc1234", "reason": "good"},
        ])
        select_override(comments, "abc1234", "pr_author", "author")
        captured = capsys.readouterr()
        assert "rejected" in captured.err
        assert "authorized" in captured.err

    def test_null_string(self):
        assert select_override("null", "abc1234", "pr_author", "author") is None

    def test_none_string(self):
        assert select_override("None", "abc1234", "pr_author", "author") is None


# ---------------------------------------------------------------------------
# determine_effective_policy
# ---------------------------------------------------------------------------

class TestDetermineEffectivePolicy:
    def test_no_failures_returns_global(self):
        verdicts = [_verdict("APOLLO"), _verdict("ATHENA")]
        assert determine_effective_policy(verdicts, {}, "pr_author") == "pr_author"

    def test_single_fail_uses_reviewer_policy(self):
        verdicts = [_verdict("SENTINEL", "FAIL"), _verdict("APOLLO")]
        policies = {"SENTINEL": "maintainers_only"}
        assert determine_effective_policy(verdicts, policies, "pr_author") == "maintainers_only"

    def test_strictest_wins(self):
        verdicts = [
            _verdict("SENTINEL", "FAIL"),
            _verdict("APOLLO", "FAIL"),
        ]
        policies = {"SENTINEL": "maintainers_only", "APOLLO": "pr_author"}
        assert determine_effective_policy(verdicts, policies, "pr_author") == "maintainers_only"

    def test_write_access_stricter_than_pr_author(self):
        verdicts = [
            _verdict("VULCAN", "FAIL"),
            _verdict("APOLLO", "FAIL"),
        ]
        policies = {"VULCAN": "write_access", "APOLLO": "pr_author"}
        assert determine_effective_policy(verdicts, policies, "pr_author") == "write_access"

    def test_missing_reviewer_falls_back_to_global(self):
        verdicts = [_verdict("UNKNOWN", "FAIL")]
        assert determine_effective_policy(verdicts, {"SENTINEL": "maintainers_only"}, "pr_author") == "pr_author"

    def test_warn_not_considered(self):
        verdicts = [
            _verdict("SENTINEL", "WARN"),
            _verdict("APOLLO", "FAIL"),
        ]
        policies = {"SENTINEL": "maintainers_only", "APOLLO": "pr_author"}
        assert determine_effective_policy(verdicts, policies, "pr_author") == "pr_author"

    def test_empty_policies_returns_global(self):
        verdicts = [_verdict("SENTINEL", "FAIL")]
        assert determine_effective_policy(verdicts, {}, "pr_author") == "pr_author"


# ---------------------------------------------------------------------------
# POLICY_STRICTNESS
# ---------------------------------------------------------------------------

class TestPolicyStrictness:
    def test_ordering(self):
        assert POLICY_STRICTNESS["pr_author"] < POLICY_STRICTNESS["write_access"]
        assert POLICY_STRICTNESS["write_access"] < POLICY_STRICTNESS["maintainers_only"]

    def test_all_policies_present(self):
        assert set(POLICY_STRICTNESS.keys()) == {"pr_author", "write_access", "maintainers_only"}
