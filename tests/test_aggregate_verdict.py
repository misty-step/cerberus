"""Tests for aggregate-verdict.py"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "aggregate-verdict.py"
FIXTURES = Path(__file__).parent / "fixtures" / "sample-verdicts"


def run_aggregate(verdict_dir: str, env_extra: dict | None = None) -> tuple[int, str, str]:
    """Run aggregate-verdict.py with a verdict directory."""
    env = os.environ.copy()
    env.pop("GH_OVERRIDE_COMMENT", None)
    env.pop("GH_OVERRIDE_COMMENTS", None)
    env.pop("GH_OVERRIDE_ACTOR_PERMISSIONS", None)
    env.pop("GH_HEAD_SHA", None)
    env.pop("GH_PR_AUTHOR", None)
    env.pop("GH_OVERRIDE_POLICY", None)
    env.pop("EXPECTED_REVIEWERS", None)
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), verdict_dir],
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


class TestAggregateBasic:
    def test_fail_when_critical_reviewer_fails(self):
        code, out, _ = run_aggregate(str(FIXTURES))
        assert code == 0
        verdict_path = Path("/tmp/council-verdict.json")
        data = json.loads(verdict_path.read_text())
        assert data["verdict"] == "FAIL"

    def test_council_verdict_json_created(self):
        run_aggregate(str(FIXTURES))
        verdict_path = Path("/tmp/council-verdict.json")
        assert verdict_path.exists()
        data = json.loads(verdict_path.read_text())
        assert data["verdict"] == "FAIL"
        assert data["stats"]["total"] == 3
        assert data["stats"]["fail"] == 1
        assert data["stats"]["warn"] == 1
        assert data["stats"]["pass"] == 1

    def test_lists_all_reviewers(self):
        code, out, _ = run_aggregate(str(FIXTURES))
        assert "APOLLO" in out
        assert "SENTINEL" in out
        assert "VULCAN" in out


class TestAggregateOverride:
    def test_override_changes_fail_to_pass(self, tmp_path):
        # Create a single FAIL verdict
        fail_verdict = {
            "reviewer": "SENTINEL", "perspective": "security",
            "verdict": "FAIL", "confidence": 0.9, "summary": "Critical issue."
        }
        (tmp_path / "security.json").write_text(json.dumps(fail_verdict))

        override = json.dumps({
            "actor": "testuser",
            "sha": "abc1234",
            "reason": "False positive, verified manually"
        })
        code, out, _ = run_aggregate(
            str(tmp_path),
            env_extra={
                "GH_OVERRIDE_COMMENT": override,
                "GH_HEAD_SHA": "abc1234",
                "GH_PR_AUTHOR": "testuser",
            },
        )
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "PASS"  # Override turned FAIL into PASS
        assert data["override"]["used"] is True

    def test_override_wrong_sha_ignored(self, tmp_path):
        fail_verdict = {
            "reviewer": "SENTINEL", "perspective": "security",
            "verdict": "FAIL", "confidence": 0.9, "summary": "Critical issue."
        }
        (tmp_path / "security.json").write_text(json.dumps(fail_verdict))

        override = json.dumps({
            "actor": "testuser",
            "sha": "wrongsha",
            "reason": "Override attempt"
        })
        code, out, _ = run_aggregate(
            str(tmp_path),
            env_extra={
                "GH_OVERRIDE_COMMENT": override,
                "GH_HEAD_SHA": "abc1234",
                "GH_PR_AUTHOR": "testuser",
            },
        )
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "FAIL"  # Still FAIL because override SHA didn't match


class TestAggregateAllPass:
    def test_all_pass(self, tmp_path):
        for name in ["a", "b", "c"]:
            v = {"reviewer": name, "perspective": name, "verdict": "PASS", "confidence": 0.9, "summary": "Good."}
            (tmp_path / f"{name}.json").write_text(json.dumps(v))
        code, out, _ = run_aggregate(str(tmp_path))
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "PASS"

    def test_warn_verdict_when_no_fail(self, tmp_path):
        (tmp_path / "a.json").write_text(
            json.dumps({"reviewer": "A", "perspective": "a", "verdict": "WARN", "confidence": 0.9, "summary": "Minor."})
        )
        (tmp_path / "b.json").write_text(
            json.dumps({"reviewer": "B", "perspective": "b", "verdict": "PASS", "confidence": 0.9, "summary": "Good."})
        )
        code, out, _ = run_aggregate(str(tmp_path))
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "WARN"


class TestCouncilFailThreshold:
    def test_single_noncritical_fail_is_warn(self, tmp_path):
        (tmp_path / "a.json").write_text(
            json.dumps(
                {
                    "reviewer": "A",
                    "perspective": "a",
                    "verdict": "FAIL",
                    "confidence": 0.9,
                    "summary": "Two major issues.",
                    "stats": {
                        "files_reviewed": 3,
                        "files_with_issues": 1,
                        "critical": 0,
                        "major": 2,
                        "minor": 0,
                        "info": 0,
                    },
                }
            )
        )
        code, out, _ = run_aggregate(str(tmp_path))
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "WARN"

    def test_two_noncritical_fails_is_fail(self, tmp_path):
        for reviewer in ["A", "B"]:
            (tmp_path / f"{reviewer}.json").write_text(
                json.dumps(
                    {
                        "reviewer": reviewer,
                        "perspective": reviewer.lower(),
                        "verdict": "FAIL",
                        "confidence": 0.9,
                        "summary": "Two major issues.",
                        "stats": {
                            "files_reviewed": 3,
                            "files_with_issues": 1,
                            "critical": 0,
                            "major": 2,
                            "minor": 0,
                            "info": 0,
                        },
                    }
                )
            )
        code, out, _ = run_aggregate(str(tmp_path))
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "FAIL"

    def test_single_critical_fail_is_fail(self, tmp_path):
        (tmp_path / "a.json").write_text(
            json.dumps(
                {
                    "reviewer": "A",
                    "perspective": "a",
                    "verdict": "FAIL",
                    "confidence": 0.9,
                    "summary": "Critical issue found.",
                    "stats": {
                        "files_reviewed": 3,
                        "files_with_issues": 1,
                        "critical": 1,
                        "major": 0,
                        "minor": 0,
                        "info": 0,
                    },
                }
            )
        )
        code, out, _ = run_aggregate(str(tmp_path))
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "FAIL"


class TestOverrideSHAValidation:
    def test_short_sha_rejected(self, tmp_path):
        fail_verdict = {
            "reviewer": "SENTINEL", "perspective": "security",
            "verdict": "FAIL", "confidence": 0.9, "summary": "Issue."
        }
        (tmp_path / "security.json").write_text(json.dumps(fail_verdict))
        override = json.dumps({
            "actor": "testuser",
            "sha": "abc",
            "reason": "Override attempt"
        })
        code, out, _ = run_aggregate(
            str(tmp_path),
            env_extra={
                "GH_OVERRIDE_COMMENT": override,
                "GH_HEAD_SHA": "abc1234567890",
                "GH_PR_AUTHOR": "testuser",
            },
        )
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "FAIL"  # Override rejected due to short SHA

    def test_prefix_sha_match_works(self, tmp_path):
        fail_verdict = {
            "reviewer": "SENTINEL", "perspective": "security",
            "verdict": "FAIL", "confidence": 0.9, "summary": "Issue."
        }
        (tmp_path / "security.json").write_text(json.dumps(fail_verdict))
        override = json.dumps({
            "actor": "testuser",
            "sha": "abc1234",
            "reason": "Verified"
        })
        code, out, _ = run_aggregate(
            str(tmp_path),
            env_extra={
                "GH_OVERRIDE_COMMENT": override,
                "GH_HEAD_SHA": "abc1234567890abcdef",
                "GH_PR_AUTHOR": "testuser",
            },
        )
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "PASS"  # Override accepted


class TestOverrideActorAuthorization:
    def test_override_rejected_when_actor_not_pr_author(self, tmp_path):
        fail_verdict = {
            "reviewer": "SENTINEL", "perspective": "security",
            "verdict": "FAIL", "confidence": 0.9, "summary": "Issue."
        }
        (tmp_path / "security.json").write_text(json.dumps(fail_verdict))
        override = json.dumps({
            "actor": "intruder",
            "sha": "abc1234",
            "reason": "Override attempt"
        })
        code, out, err = run_aggregate(
            str(tmp_path),
            env_extra={
                "GH_OVERRIDE_COMMENT": override,
                "GH_HEAD_SHA": "abc1234",
                "GH_PR_AUTHOR": "trusted-author",
                "GH_OVERRIDE_POLICY": "pr_author",
            },
        )
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "FAIL"
        assert data["override"]["used"] is False
        assert "rejected by policy" in err

    def test_override_accepted_when_actor_is_pr_author(self, tmp_path):
        fail_verdict = {
            "reviewer": "SENTINEL", "perspective": "security",
            "verdict": "FAIL", "confidence": 0.9, "summary": "Issue."
        }
        (tmp_path / "security.json").write_text(json.dumps(fail_verdict))
        override = json.dumps({
            "actor": "trusted-author",
            "sha": "abc1234",
            "reason": "Verified"
        })
        code, out, _ = run_aggregate(
            str(tmp_path),
            env_extra={
                "GH_OVERRIDE_COMMENT": override,
                "GH_HEAD_SHA": "abc1234",
                "GH_PR_AUTHOR": "trusted-author",
                "GH_OVERRIDE_POLICY": "pr_author",
            },
        )
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "PASS"
        assert data["override"]["used"] is True

    def test_override_case_insensitive_actor_match(self, tmp_path):
        fail_verdict = {
            "reviewer": "SENTINEL", "perspective": "security",
            "verdict": "FAIL", "confidence": 0.9, "summary": "Issue."
        }
        (tmp_path / "security.json").write_text(json.dumps(fail_verdict))
        override = json.dumps({
            "actor": "TrustedAuthor",
            "sha": "abc1234",
            "reason": "Verified"
        })
        code, out, _ = run_aggregate(
            str(tmp_path),
            env_extra={
                "GH_OVERRIDE_COMMENT": override,
                "GH_HEAD_SHA": "abc1234",
                "GH_PR_AUTHOR": "trustedauthor",
                "GH_OVERRIDE_POLICY": "pr_author",
            },
        )
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "PASS"
        assert data["override"]["used"] is True

    def test_override_rejected_when_pr_author_unset(self, tmp_path):
        fail_verdict = {
            "reviewer": "SENTINEL", "perspective": "security",
            "verdict": "FAIL", "confidence": 0.9, "summary": "Issue."
        }
        (tmp_path / "security.json").write_text(json.dumps(fail_verdict))
        override = json.dumps({
            "actor": "testuser",
            "sha": "abc1234",
            "reason": "Override attempt"
        })
        code, out, err = run_aggregate(
            str(tmp_path),
            env_extra={
                "GH_OVERRIDE_COMMENT": override,
                "GH_HEAD_SHA": "abc1234",
                "GH_OVERRIDE_POLICY": "pr_author",
            },
        )
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "FAIL"
        assert data["override"]["used"] is False
        assert "rejected by policy" in err

    def test_default_policy_is_pr_author(self, tmp_path):
        fail_verdict = {
            "reviewer": "SENTINEL", "perspective": "security",
            "verdict": "FAIL", "confidence": 0.9, "summary": "Issue."
        }
        (tmp_path / "security.json").write_text(json.dumps(fail_verdict))
        override = json.dumps({
            "actor": "trusted-author",
            "sha": "abc1234",
            "reason": "Verified"
        })
        code, out, _ = run_aggregate(
            str(tmp_path),
            env_extra={
                "GH_OVERRIDE_COMMENT": override,
                "GH_HEAD_SHA": "abc1234",
                "GH_PR_AUTHOR": "trusted-author",
            },
        )
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "PASS"
        assert data["override"]["used"] is True

    def test_write_access_policy_rejected(self, tmp_path):
        fail_verdict = {
            "reviewer": "SENTINEL", "perspective": "security",
            "verdict": "FAIL", "confidence": 0.9, "summary": "Issue."
        }
        (tmp_path / "security.json").write_text(json.dumps(fail_verdict))
        override = json.dumps({
            "actor": "random-user",
            "sha": "abc1234",
            "reason": "Maintainer approved"
        })
        code, out, _ = run_aggregate(
            str(tmp_path),
            env_extra={
                "GH_OVERRIDE_COMMENT": override,
                "GH_HEAD_SHA": "abc1234",
                "GH_PR_AUTHOR": "different-author",
                "GH_OVERRIDE_POLICY": "write_access",
            },
        )
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "FAIL"
        assert data["override"]["used"] is False

    def test_maintainers_only_policy_rejected(self, tmp_path):
        fail_verdict = {
            "reviewer": "SENTINEL", "perspective": "security",
            "verdict": "FAIL", "confidence": 0.9, "summary": "Issue."
        }
        (tmp_path / "security.json").write_text(json.dumps(fail_verdict))
        override = json.dumps({
            "actor": "another-user",
            "sha": "abc1234",
            "reason": "Maintainer approved"
        })
        code, out, _ = run_aggregate(
            str(tmp_path),
            env_extra={
                "GH_OVERRIDE_COMMENT": override,
                "GH_HEAD_SHA": "abc1234",
                "GH_PR_AUTHOR": "different-author",
                "GH_OVERRIDE_POLICY": "maintainers_only",
            },
        )
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "FAIL"
        assert data["override"]["used"] is False

    def test_unknown_policy_rejects_override(self, tmp_path):
        fail_verdict = {
            "reviewer": "SENTINEL", "perspective": "security",
            "verdict": "FAIL", "confidence": 0.9, "summary": "Issue."
        }
        (tmp_path / "security.json").write_text(json.dumps(fail_verdict))
        override = json.dumps({
            "actor": "trusted-author",
            "sha": "abc1234",
            "reason": "Override attempt"
        })
        code, out, _ = run_aggregate(
            str(tmp_path),
            env_extra={
                "GH_OVERRIDE_COMMENT": override,
                "GH_HEAD_SHA": "abc1234",
                "GH_PR_AUTHOR": "trusted-author",
                "GH_OVERRIDE_POLICY": "unknown_policy",
            },
        )
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "FAIL"
        assert data["override"]["used"] is False


class TestAggregateErrors:
    def test_missing_dir(self, tmp_path):
        code, _, err = run_aggregate(str(tmp_path / "nonexistent"))
        assert code == 2

    def test_empty_dir(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        code, _, err = run_aggregate(str(empty))
        assert code == 2


def test_read_json_handles_corrupt_file(tmp_path):
    """Binary/corrupt verdict file is skipped, not crash."""
    (tmp_path / "corrupt.json").write_bytes(b"\x00\x01\x02\x03")
    code, _, err = run_aggregate(str(tmp_path))
    assert code == 0
    assert "skipped" in err.lower()
    data = json.loads(Path("/tmp/council-verdict.json").read_text())
    assert data["verdict"] == "SKIP"
    assert len(data.get("skipped_artifacts", [])) == 1


def test_warns_on_missing_reviewers(tmp_path):
    (tmp_path / "apollo.json").write_text(
        json.dumps({"reviewer": "APOLLO", "perspective": "correctness", "verdict": "PASS", "confidence": 0.9, "summary": "ok"})
    )
    (tmp_path / "athena.json").write_text(
        json.dumps({"reviewer": "ATHENA", "perspective": "architecture", "verdict": "PASS", "confidence": 0.9, "summary": "ok"})
    )

    code, out, err = run_aggregate(
        str(tmp_path),
        env_extra={"EXPECTED_REVIEWERS": "APOLLO,ATHENA,SENTINEL"},
    )
    assert code == 0
    assert "expected 3 reviewers (APOLLO, ATHENA, SENTINEL), got 2 verdict files" in err


def test_detects_fallback_verdicts(tmp_path):
    """With default warn policy, parse failures are reclassified as SKIP (#216)."""
    (tmp_path / "apollo.json").write_text(
        json.dumps(
            {
                "reviewer": "APOLLO",
                "perspective": "unknown",
                "verdict": "FAIL",
                "confidence": 0.0,
                "summary": "Review output could not be parsed: no ```json block found",
            }
        )
    )
    (tmp_path / "athena.json").write_text(
        json.dumps({"reviewer": "ATHENA", "perspective": "architecture", "verdict": "PASS", "confidence": 0.9, "summary": "ok"})
    )

    code, out, err = run_aggregate(
        str(tmp_path),
        env_extra={"EXPECTED_REVIEWERS": "APOLLO,ATHENA"},
    )
    assert code == 0
    assert "fallback verdicts detected" in err
    assert "APOLLO" in err
    # Default policy is warn: parse failures reclassified as SKIP, so council is PASS
    assert "Council Verdict: PASS" in out
    assert "parse-failure verdict(s) reclassified as SKIP" in err


def test_fallback_verdicts_with_fail_policy(tmp_path):
    """With fail policy, parse failures still count as FAIL (legacy behavior)."""
    (tmp_path / "apollo.json").write_text(
        json.dumps(
            {
                "reviewer": "APOLLO",
                "perspective": "unknown",
                "verdict": "FAIL",
                "confidence": 0.0,
                "summary": "Review output could not be parsed: no ```json block found",
            }
        )
    )
    (tmp_path / "athena.json").write_text(
        json.dumps({"reviewer": "ATHENA", "perspective": "architecture", "verdict": "PASS", "confidence": 0.9, "summary": "ok"})
    )

    code, out, err = run_aggregate(
        str(tmp_path),
        env_extra={
            "EXPECTED_REVIEWERS": "APOLLO,ATHENA",
            "PARSE_FAILURE_POLICY": "fail",
        },
    )
    assert code == 0
    assert "Council Verdict: FAIL" in out


def test_preserves_reviewer_runtime_seconds(tmp_path):
    (tmp_path / "apollo.json").write_text(
        json.dumps(
            {
                "reviewer": "APOLLO",
                "perspective": "correctness",
                "verdict": "PASS",
                "confidence": 0.9,
                "summary": "ok",
                "runtime_seconds": 37,
            }
        )
    )

    code, out, err = run_aggregate(str(tmp_path))
    assert code == 0
    data = json.loads(Path("/tmp/council-verdict.json").read_text())
    assert data["reviewers"][0]["runtime_seconds"] == 37


def test_propagates_model_metadata(tmp_path):
    """model_used, primary_model, fallback_used should pass through to council verdict."""
    (tmp_path / "apollo.json").write_text(
        json.dumps(
            {
                "reviewer": "APOLLO",
                "perspective": "correctness",
                "verdict": "PASS",
                "confidence": 0.9,
                "summary": "ok",
                "model_used": "openrouter/moonshotai/kimi-k2.5",
                "primary_model": "openrouter/moonshotai/kimi-k2.5",
                "fallback_used": False,
            }
        )
    )

    code, _out, _err = run_aggregate(str(tmp_path))
    assert code == 0
    data = json.loads(Path("/tmp/council-verdict.json").read_text())
    reviewer = data["reviewers"][0]
    assert reviewer["model_used"] == "openrouter/moonshotai/kimi-k2.5"
    assert reviewer["primary_model"] == "openrouter/moonshotai/kimi-k2.5"
    assert reviewer["fallback_used"] is False


def test_propagates_fallback_model_metadata(tmp_path):
    """Fallback model metadata should propagate correctly."""
    (tmp_path / "sentinel.json").write_text(
        json.dumps(
            {
                "reviewer": "SENTINEL",
                "perspective": "security",
                "verdict": "PASS",
                "confidence": 0.85,
                "summary": "ok",
                "model_used": "openrouter/deepseek/deepseek-v3.2",
                "primary_model": "openrouter/moonshotai/kimi-k2.5",
                "fallback_used": True,
            }
        )
    )

    code, _out, _err = run_aggregate(str(tmp_path))
    assert code == 0
    data = json.loads(Path("/tmp/council-verdict.json").read_text())
    reviewer = data["reviewers"][0]
    assert reviewer["model_used"] == "openrouter/deepseek/deepseek-v3.2"
    assert reviewer["primary_model"] == "openrouter/moonshotai/kimi-k2.5"
    assert reviewer["fallback_used"] is True


def test_missing_model_metadata_defaults_to_none(tmp_path):
    """Verdicts without model metadata should have None values in council output."""
    (tmp_path / "apollo.json").write_text(
        json.dumps(
            {
                "reviewer": "APOLLO",
                "perspective": "correctness",
                "verdict": "PASS",
                "confidence": 0.9,
                "summary": "ok",
            }
        )
    )

    code, _out, _err = run_aggregate(str(tmp_path))
    assert code == 0
    data = json.loads(Path("/tmp/council-verdict.json").read_text())
    reviewer = data["reviewers"][0]
    assert reviewer["model_used"] is None
    assert reviewer["primary_model"] is None
    assert reviewer["fallback_used"] is None


def test_partial_model_metadata_propagates_present_values(tmp_path):
    """Only model_used present; other fields default to None."""
    (tmp_path / "apollo.json").write_text(
        json.dumps(
            {
                "reviewer": "APOLLO",
                "perspective": "correctness",
                "verdict": "PASS",
                "confidence": 0.9,
                "summary": "ok",
                "model_used": "openrouter/moonshotai/kimi-k2.5",
            }
        )
    )

    code, _out, _err = run_aggregate(str(tmp_path))
    assert code == 0
    data = json.loads(Path("/tmp/council-verdict.json").read_text())
    reviewer = data["reviewers"][0]
    assert reviewer["model_used"] == "openrouter/moonshotai/kimi-k2.5"
    assert reviewer["primary_model"] is None
    assert reviewer["fallback_used"] is None


# ---------------------------------------------------------------------------
# Phase 2: Unit tests via importlib (no subprocess)
# ---------------------------------------------------------------------------

from conftest import aggregate_verdict
from lib.overrides import Override

_parse_override = aggregate_verdict.parse_override
_aggregate = aggregate_verdict.aggregate
_validate_actor = aggregate_verdict.validate_actor
_is_fallback_verdict = aggregate_verdict.is_fallback_verdict
_parse_expected_reviewers = aggregate_verdict.parse_expected_reviewers


def _verdict(name: str, result: str = "PASS", **extra) -> dict:
    """Helper to build a minimal verdict dict."""
    return {"reviewer": name, "perspective": name.lower(), "verdict": result, "summary": "ok", **extra}


# --- parse_override unit tests ---

class TestParseOverrideUnit:
    def test_none_input(self):
        assert _parse_override(None, "abc1234") is None

    def test_empty_string(self):
        assert _parse_override("", "abc1234") is None

    def test_null_string(self):
        assert _parse_override("null", "abc1234") is None

    def test_none_string(self):
        assert _parse_override("None", "abc1234") is None

    def test_whitespace_only(self):
        assert _parse_override("   ", "abc1234") is None

    def test_invalid_json(self):
        assert _parse_override("{not json}", "abc1234") is None

    def test_missing_sha(self):
        raw = json.dumps({"actor": "user", "reason": "good reason"})
        assert _parse_override(raw, "abc1234") is None

    def test_missing_reason(self):
        raw = json.dumps({"actor": "user", "sha": "abc1234"})
        assert _parse_override(raw, "abc1234") is None

    def test_sha_too_short(self):
        raw = json.dumps({"actor": "user", "sha": "abc", "reason": "ok"})
        assert _parse_override(raw, "abc1234") is None

    def test_sha_mismatch(self):
        raw = json.dumps({"actor": "user", "sha": "def7890", "reason": "ok"})
        assert _parse_override(raw, "abc1234") is None

    def test_valid_override(self):
        raw = json.dumps({"actor": "user", "sha": "abc1234", "reason": "verified"})
        result = _parse_override(raw, "abc1234567890")
        assert result == Override(actor="user", sha="abc1234", reason="verified")

    def test_no_head_sha_skips_check(self):
        raw = json.dumps({"actor": "user", "sha": "abc1234", "reason": "ok"})
        result = _parse_override(raw, None)
        assert result is not None
        assert result.sha == "abc1234"

    def test_body_parsing_extracts_sha_and_reason(self):
        raw = json.dumps({
            "actor": "user",
            "body": "/council override sha=abc1234\nReason: False positive confirmed",
        })
        result = _parse_override(raw, "abc1234567890")
        assert result is not None
        assert result.sha == "abc1234"
        assert result.reason == "False positive confirmed"

    def test_body_parsing_remainder_as_reason(self):
        raw = json.dumps({
            "actor": "user",
            "body": "/council override sha=abc1234\nThis is a false positive and safe to merge",
        })
        result = _parse_override(raw, "abc1234567890")
        assert result is not None
        assert result.reason == "This is a false positive and safe to merge"

    def test_body_sha_does_not_override_explicit_sha(self):
        raw = json.dumps({
            "actor": "user",
            "sha": "explicit1",
            "body": "/council override sha=body1234\nReason: test",
        })
        result = _parse_override(raw, "explicit1234567890")
        assert result is not None
        assert result.sha == "explicit1"

    def test_author_field_fallback(self):
        raw = json.dumps({"author": "alt-user", "sha": "abc1234", "reason": "ok"})
        result = _parse_override(raw, "abc1234")
        assert result.actor == "alt-user"

    def test_actor_defaults_to_unknown(self):
        raw = json.dumps({"sha": "abc1234", "reason": "ok"})
        result = _parse_override(raw, "abc1234")
        assert result.actor == "unknown"


# --- aggregate() unit tests ---

class TestAggregateUnit:
    def test_all_pass(self):
        verdicts = [_verdict("A"), _verdict("B"), _verdict("C")]
        result = _aggregate(verdicts)
        assert result["verdict"] == "PASS"
        assert result["stats"]["pass"] == 3
        assert result["stats"]["fail"] == 0

    def test_fail_without_evidence_blocks_conservatively(self):
        verdicts = [_verdict("A"), _verdict("B", "FAIL"), _verdict("C")]
        result = _aggregate(verdicts)
        assert result["verdict"] == "FAIL"
        assert result["stats"]["fail"] == 1

    def test_single_noncritical_fail_is_warn(self):
        verdicts = [
            _verdict("A"),
            _verdict("B", "FAIL", stats={"critical": 0, "major": 2, "minor": 0}),
        ]
        result = _aggregate(verdicts)
        assert result["verdict"] == "WARN"
        assert result["stats"]["fail"] == 1

    def test_two_noncritical_fails_is_fail(self):
        verdicts = [
            _verdict("A", "FAIL", stats={"critical": 0, "major": 2, "minor": 0}),
            _verdict("B", "FAIL", stats={"critical": 0, "major": 2, "minor": 0}),
        ]
        result = _aggregate(verdicts)
        assert result["verdict"] == "FAIL"
        assert result["stats"]["fail"] == 2

    def test_single_critical_fail_is_fail(self):
        verdicts = [
            _verdict("A"),
            _verdict("B", "FAIL", stats={"critical": 1, "major": 0, "minor": 0}),
        ]
        result = _aggregate(verdicts)
        assert result["verdict"] == "FAIL"

    def test_warn_without_fail(self):
        verdicts = [_verdict("A"), _verdict("B", "WARN")]
        result = _aggregate(verdicts)
        assert result["verdict"] == "WARN"
        assert result["stats"]["warn"] == 1

    def test_fail_overrides_warn(self):
        verdicts = [_verdict("A", "FAIL"), _verdict("B", "WARN")]
        result = _aggregate(verdicts)
        assert result["verdict"] == "FAIL"

    def test_override_turns_fail_to_pass(self):
        verdicts = [_verdict("A", "FAIL")]
        override = Override(actor="user", sha="abc1234", reason="ok")
        result = _aggregate(verdicts, override)
        assert result["verdict"] == "PASS"
        assert result["override"]["used"] is True

    def test_override_with_warn_stays_warn(self):
        verdicts = [_verdict("A", "FAIL"), _verdict("B", "WARN")]
        override = Override(actor="user", sha="abc1234", reason="ok")
        result = _aggregate(verdicts, override)
        assert result["verdict"] == "WARN"

    def test_no_override_marks_unused(self):
        verdicts = [_verdict("A")]
        result = _aggregate(verdicts)
        assert result["override"]["used"] is False

    def test_summary_includes_counts(self):
        verdicts = [_verdict("A"), _verdict("B", "FAIL")]
        result = _aggregate(verdicts)
        assert "2 reviewers" in result["summary"]
        assert "Failures: 1" in result["summary"]

    def test_summary_includes_override_info(self):
        verdicts = [_verdict("A", "FAIL")]
        override = Override(actor="user", sha="abc1234", reason="ok")
        result = _aggregate(verdicts, override)
        assert "Override by user" in result["summary"]

    def test_empty_verdicts(self):
        result = _aggregate([])
        assert result["verdict"] == "PASS"
        assert result["stats"]["total"] == 0

    def test_reviewers_preserved_in_output(self):
        verdicts = [_verdict("APOLLO"), _verdict("ATHENA")]
        result = _aggregate(verdicts)
        assert len(result["reviewers"]) == 2
        assert result["reviewers"][0]["reviewer"] == "APOLLO"


# --- validate_actor unit tests ---

class TestValidateActorUnit:
    def test_pr_author_match(self):
        assert _validate_actor("user", "pr_author", "user") is True

    def test_pr_author_case_insensitive(self):
        assert _validate_actor("User", "pr_author", "user") is True

    def test_pr_author_mismatch(self):
        assert _validate_actor("other", "pr_author", "user") is False

    def test_pr_author_none(self):
        assert _validate_actor("user", "pr_author", None) is False

    def test_unknown_policy_rejects(self):
        assert _validate_actor("user", "unknown", "user") is False


# --- is_fallback_verdict unit tests ---

class TestIsFallbackVerdictUnit:
    def test_detects_fallback(self):
        v = {"summary": "Review output could not be parsed: error", "confidence": 0.0}
        assert _is_fallback_verdict(v) is True

    def test_normal_verdict_not_fallback(self):
        v = {"summary": "All good", "confidence": 0.9}
        assert _is_fallback_verdict(v) is False

    def test_zero_confidence_wrong_prefix(self):
        v = {"summary": "Something else", "confidence": 0.0}
        assert _is_fallback_verdict(v) is False

    def test_right_prefix_nonzero_confidence(self):
        v = {"summary": "Review output could not be parsed: err", "confidence": 0.5}
        assert _is_fallback_verdict(v) is False

    def test_missing_summary(self):
        assert _is_fallback_verdict({"confidence": 0.0}) is False

    def test_non_string_summary(self):
        assert _is_fallback_verdict({"summary": 42, "confidence": 0.0}) is False


# --- parse_expected_reviewers unit tests ---

class TestParseExpectedReviewersUnit:
    def test_none(self):
        assert _parse_expected_reviewers(None) == []

    def test_empty(self):
        assert _parse_expected_reviewers("") == []

    def test_single(self):
        assert _parse_expected_reviewers("APOLLO") == ["APOLLO"]

    def test_multiple(self):
        assert _parse_expected_reviewers("APOLLO,ATHENA,SENTINEL") == ["APOLLO", "ATHENA", "SENTINEL"]

    def test_strips_whitespace(self):
        assert _parse_expected_reviewers(" APOLLO , ATHENA ") == ["APOLLO", "ATHENA"]

    def test_ignores_empty_segments(self):
        assert _parse_expected_reviewers("APOLLO,,ATHENA,") == ["APOLLO", "ATHENA"]


# --- Integration: parse → aggregate pipeline ---

class TestPipelineIntegration:
    """End-to-end: parse raw reviewer output, then aggregate verdicts."""

    def test_parse_then_aggregate_pass(self, tmp_path):
        from conftest import parse_review
        # Simulate three PASS reviews
        for name in ["APOLLO", "ATHENA", "SENTINEL"]:
            raw = json.dumps({
                "reviewer": name, "perspective": name.lower(), "verdict": "PASS",
                "confidence": 0.9, "summary": "Looks good.",
                "findings": [],
                "stats": {"files_reviewed": 3, "files_with_issues": 0,
                          "critical": 0, "major": 0, "minor": 0, "info": 0},
            })
            text = f"Review notes.\n```json\n{raw}\n```\n"
            # Use subprocess to parse (mirrors real pipeline)
            result = subprocess.run(
                [sys.executable, str(Path(__file__).parent.parent / "scripts" / "parse-review.py"),
                 "--reviewer", name],
                input=text, capture_output=True, text=True,
            )
            assert result.returncode == 0
            (tmp_path / f"{name.lower()}.json").write_text(result.stdout)

        # Aggregate
        council = _aggregate([json.loads((tmp_path / f).read_text()) for f in ["apollo.json", "athena.json", "sentinel.json"]])
        assert council["verdict"] == "PASS"
        assert council["stats"]["total"] == 3

    def test_parse_then_aggregate_with_critical(self, tmp_path):
        # One reviewer finds a critical issue
        raw_fail = json.dumps({
            "reviewer": "SENTINEL", "perspective": "security", "verdict": "PASS",
            "confidence": 0.95, "summary": "Critical found.",
            "findings": [{
                "severity": "critical", "category": "injection", "file": "a.py",
                "line": 10, "title": "SQL injection", "description": "d", "suggestion": "s",
            }],
            "stats": {"files_reviewed": 1, "files_with_issues": 1,
                      "critical": 1, "major": 0, "minor": 0, "info": 0},
        })
        text = f"```json\n{raw_fail}\n```"
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent.parent / "scripts" / "parse-review.py"),
             "--reviewer", "SENTINEL"],
            input=text, capture_output=True, text=True,
        )
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        # Verdict consistency should have rewritten PASS → FAIL
        assert parsed["verdict"] == "FAIL"

        # Pass reviewer
        raw_pass = json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness", "verdict": "PASS",
            "confidence": 0.9, "summary": "ok",
            "findings": [],
            "stats": {"files_reviewed": 1, "files_with_issues": 0,
                      "critical": 0, "major": 0, "minor": 0, "info": 0},
        })
        result2 = subprocess.run(
            [sys.executable, str(Path(__file__).parent.parent / "scripts" / "parse-review.py"),
             "--reviewer", "APOLLO"],
            input=f"```json\n{raw_pass}\n```", capture_output=True, text=True,
        )
        parsed2 = json.loads(result2.stdout)

        council = _aggregate([parsed, parsed2])
        assert council["verdict"] == "FAIL"
        assert council["stats"]["fail"] == 1

    def test_parse_then_aggregate_single_noncritical_fail_is_warn(self, tmp_path):
        raw_fail = json.dumps(
            {
                "reviewer": "SENTINEL",
                "perspective": "security",
                "verdict": "PASS",
                "confidence": 0.95,
                "summary": "Two major issues found.",
                "findings": [
                    {
                        "severity": "major",
                        "category": "auth",
                        "file": "a.py",
                        "line": 1,
                        "title": "Issue 1",
                        "description": "d",
                        "suggestion": "s",
                    },
                    {
                        "severity": "major",
                        "category": "auth",
                        "file": "a.py",
                        "line": 2,
                        "title": "Issue 2",
                        "description": "d",
                        "suggestion": "s",
                    },
                ],
                "stats": {
                    "files_reviewed": 1,
                    "files_with_issues": 1,
                    "critical": 0,
                    "major": 2,
                    "minor": 0,
                    "info": 0,
                },
            }
        )
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent.parent / "scripts" / "parse-review.py"),
             "--reviewer", "SENTINEL"],
            input=f"```json\n{raw_fail}\n```", capture_output=True, text=True,
        )
        parsed = json.loads(result.stdout)
        assert parsed["verdict"] == "FAIL"

        raw_pass = json.dumps(
            {
                "reviewer": "APOLLO",
                "perspective": "correctness",
                "verdict": "PASS",
                "confidence": 0.9,
                "summary": "ok",
                "findings": [],
                "stats": {
                    "files_reviewed": 1,
                    "files_with_issues": 0,
                    "critical": 0,
                    "major": 0,
                    "minor": 0,
                    "info": 0,
                },
            }
        )
        result2 = subprocess.run(
            [sys.executable, str(Path(__file__).parent.parent / "scripts" / "parse-review.py"),
             "--reviewer", "APOLLO"],
            input=f"```json\n{raw_pass}\n```", capture_output=True, text=True,
        )
        parsed2 = json.loads(result2.stdout)

        council = _aggregate([parsed, parsed2])
        assert council["verdict"] == "WARN"
        assert council["stats"]["fail"] == 1


class TestSkipVerdicts:
    def test_skip_does_not_cause_fail(self, tmp_path):
        """A single SKIP verdict should not cause council to FAIL."""
        skip_verdict = {
            "reviewer": "SYSTEM", "perspective": "error",
            "verdict": "SKIP", "confidence": 0.0, "summary": "API error occurred."
        }
        (tmp_path / "error.json").write_text(json.dumps(skip_verdict))
        code, out, _ = run_aggregate(str(tmp_path))
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "SKIP"

    def test_all_skips_results_in_skip_verdict(self, tmp_path):
        """If all reviewers skip, council verdict should be SKIP."""
        for name in ["a", "b", "c"]:
            v = {"reviewer": name, "perspective": name, "verdict": "SKIP", "confidence": 0.0, "summary": "API error."}
            (tmp_path / f"{name}.json").write_text(json.dumps(v))
        code, out, _ = run_aggregate(str(tmp_path))
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "SKIP"
        assert data["stats"]["skip"] == 3

    def test_mixed_skip_and_pass_results_in_pass(self, tmp_path):
        """SKIP + PASS should result in PASS (no failures or warnings)."""
        (tmp_path / "a.json").write_text(
            json.dumps({"reviewer": "A", "perspective": "a", "verdict": "SKIP", "confidence": 0.0, "summary": "API error."})
        )
        (tmp_path / "b.json").write_text(
            json.dumps({"reviewer": "B", "perspective": "b", "verdict": "PASS", "confidence": 0.9, "summary": "Good."})
        )
        code, out, _ = run_aggregate(str(tmp_path))
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "PASS"
        assert data["stats"]["skip"] == 1
        assert data["stats"]["pass"] == 1

    def test_mixed_skip_and_fail_results_in_fail(self, tmp_path):
        """SKIP + FAIL should result in FAIL."""
        (tmp_path / "a.json").write_text(
            json.dumps({"reviewer": "A", "perspective": "a", "verdict": "SKIP", "confidence": 0.0, "summary": "API error."})
        )
        (tmp_path / "b.json").write_text(
            json.dumps({"reviewer": "B", "perspective": "b", "verdict": "FAIL", "confidence": 0.9, "summary": "Bad."})
        )
        code, out, _ = run_aggregate(str(tmp_path))
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "FAIL"
        assert data["stats"]["skip"] == 1
        assert data["stats"]["fail"] == 1

    def test_mixed_skip_and_warn_results_in_warn(self, tmp_path):
        """SKIP + WARN should result in WARN (no failures)."""
        (tmp_path / "a.json").write_text(
            json.dumps({"reviewer": "A", "perspective": "a", "verdict": "SKIP", "confidence": 0.0, "summary": "API error."})
        )
        (tmp_path / "b.json").write_text(
            json.dumps({"reviewer": "B", "perspective": "b", "verdict": "WARN", "confidence": 0.9, "summary": "Minor."})
        )
        code, out, _ = run_aggregate(str(tmp_path))
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "WARN"
        assert data["stats"]["skip"] == 1
        assert data["stats"]["warn"] == 1

    def test_skip_counted_in_summary(self, tmp_path):
        """SKIP count should appear in summary text."""
        (tmp_path / "a.json").write_text(
            json.dumps({"reviewer": "A", "perspective": "a", "verdict": "SKIP", "confidence": 0.0, "summary": "API error."})
        )
        code, out, _ = run_aggregate(str(tmp_path))
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert "skipped: 1" in data["summary"]

    def test_timeout_skips_are_named_in_summary(self, tmp_path):
        (tmp_path / "apollo.json").write_text(
            json.dumps(
                {
                    "reviewer": "APOLLO",
                    "perspective": "correctness",
                    "verdict": "SKIP",
                    "confidence": 0.0,
                    "summary": "Review skipped due to timeout after 120s.",
                }
            )
        )
        (tmp_path / "athena.json").write_text(
            json.dumps({"reviewer": "ATHENA", "perspective": "architecture", "verdict": "PASS", "confidence": 0.9, "summary": "Good."})
        )
        code, out, _ = run_aggregate(str(tmp_path))
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert "Timed out reviewers: APOLLO." in data["summary"]

    def test_all_four_verdict_types_in_stats(self, tmp_path):
        """Stats should include all four verdict types."""
        (tmp_path / "pass.json").write_text(
            json.dumps({"reviewer": "P", "perspective": "p", "verdict": "PASS", "confidence": 0.9, "summary": "Good."})
        )
        (tmp_path / "warn.json").write_text(
            json.dumps({"reviewer": "W", "perspective": "w", "verdict": "WARN", "confidence": 0.9, "summary": "Minor."})
        )
        (tmp_path / "fail.json").write_text(
            json.dumps({"reviewer": "F", "perspective": "f", "verdict": "FAIL", "confidence": 0.9, "summary": "Bad."})
        )
        (tmp_path / "skip.json").write_text(
            json.dumps({"reviewer": "S", "perspective": "s", "verdict": "SKIP", "confidence": 0.0, "summary": "Error."})
        )
        code, out, _ = run_aggregate(str(tmp_path))
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["stats"]["pass"] == 1
        assert data["stats"]["warn"] == 1
        assert data["stats"]["fail"] == 1
        assert data["stats"]["skip"] == 1
        assert data["stats"]["total"] == 4


# ---------------------------------------------------------------------------
# Per-reviewer override policies (Issue #24)
# ---------------------------------------------------------------------------

_determine_effective_policy = aggregate_verdict.determine_effective_policy


class TestDetermineEffectivePolicy:
    """Unit tests for determine_effective_policy()."""

    def test_no_failing_reviewers_returns_global(self):
        verdicts = [_verdict("APOLLO"), _verdict("ATHENA")]
        policies = {"APOLLO": "pr_author", "ATHENA": "pr_author"}
        assert _determine_effective_policy(verdicts, policies, "pr_author") == "pr_author"

    def test_single_fail_uses_reviewer_policy(self):
        verdicts = [_verdict("SENTINEL", "FAIL"), _verdict("APOLLO")]
        policies = {"SENTINEL": "maintainers_only", "APOLLO": "pr_author"}
        assert _determine_effective_policy(verdicts, policies, "pr_author") == "maintainers_only"

    def test_strictest_policy_wins(self):
        verdicts = [
            _verdict("SENTINEL", "FAIL"),
            _verdict("APOLLO", "FAIL"),
        ]
        policies = {"SENTINEL": "maintainers_only", "APOLLO": "pr_author"}
        assert _determine_effective_policy(verdicts, policies, "pr_author") == "maintainers_only"

    def test_write_access_stricter_than_pr_author(self):
        verdicts = [
            _verdict("VULCAN", "FAIL"),
            _verdict("APOLLO", "FAIL"),
        ]
        policies = {"VULCAN": "write_access", "APOLLO": "pr_author"}
        assert _determine_effective_policy(verdicts, policies, "pr_author") == "write_access"

    def test_maintainers_only_stricter_than_write_access(self):
        verdicts = [
            _verdict("SENTINEL", "FAIL"),
            _verdict("VULCAN", "FAIL"),
        ]
        policies = {"SENTINEL": "maintainers_only", "VULCAN": "write_access"}
        assert _determine_effective_policy(verdicts, policies, "pr_author") == "maintainers_only"

    def test_missing_reviewer_policy_falls_back_to_global(self):
        verdicts = [_verdict("UNKNOWN", "FAIL")]
        policies = {"SENTINEL": "maintainers_only"}
        assert _determine_effective_policy(verdicts, policies, "pr_author") == "pr_author"

    def test_warn_reviewer_not_considered(self):
        verdicts = [
            _verdict("SENTINEL", "WARN"),
            _verdict("APOLLO", "FAIL"),
        ]
        policies = {"SENTINEL": "maintainers_only", "APOLLO": "pr_author"}
        # SENTINEL is WARN, not FAIL — only APOLLO's policy applies
        assert _determine_effective_policy(verdicts, policies, "pr_author") == "pr_author"

    def test_noncritical_fail_reviewer_included(self):
        verdicts = [
            _verdict("SENTINEL", "FAIL", stats={"critical": 0, "major": 2, "minor": 0}),
        ]
        policies = {"SENTINEL": "maintainers_only"}
        # Even noncritical FAILs contribute to policy determination
        assert _determine_effective_policy(verdicts, policies, "pr_author") == "maintainers_only"

    def test_empty_policies_returns_global(self):
        verdicts = [_verdict("SENTINEL", "FAIL")]
        assert _determine_effective_policy(verdicts, {}, "pr_author") == "pr_author"


class TestValidateActorWriteAccess:
    """validate_actor with write_access policy."""

    def test_write_permission_accepted(self):
        assert _validate_actor("user", "write_access", "other", "write") is True

    def test_admin_permission_accepted(self):
        assert _validate_actor("user", "write_access", "other", "admin") is True

    def test_maintain_permission_accepted(self):
        assert _validate_actor("user", "write_access", "other", "maintain") is True

    def test_read_permission_rejected(self):
        assert _validate_actor("user", "write_access", "other", "read") is False

    def test_none_permission_rejected(self):
        assert _validate_actor("user", "write_access", "other", "none") is False

    def test_missing_permission_rejected(self):
        assert _validate_actor("user", "write_access", "other", None) is False


class TestValidateActorMaintainersOnly:
    """validate_actor with maintainers_only policy."""

    def test_admin_accepted(self):
        assert _validate_actor("user", "maintainers_only", "other", "admin") is True

    def test_maintain_accepted(self):
        assert _validate_actor("user", "maintainers_only", "other", "maintain") is True

    def test_write_rejected(self):
        assert _validate_actor("user", "maintainers_only", "other", "write") is False

    def test_read_rejected(self):
        assert _validate_actor("user", "maintainers_only", "other", "read") is False

    def test_none_rejected(self):
        assert _validate_actor("user", "maintainers_only", "other", "none") is False


class TestPerReviewerOverrideIntegration:
    """Subprocess integration tests for per-reviewer override policies."""

    def test_sentinel_fail_blocks_pr_author_override(self, tmp_path):
        """SENTINEL (maintainers_only) FAIL should block override from pr_author."""
        (tmp_path / "sentinel.json").write_text(json.dumps({
            "reviewer": "SENTINEL", "perspective": "security",
            "verdict": "FAIL", "confidence": 0.9, "summary": "Critical security issue.",
            "stats": {"critical": 1, "major": 0, "minor": 0, "info": 0},
        }))
        (tmp_path / "apollo.json").write_text(json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness",
            "verdict": "PASS", "confidence": 0.9, "summary": "ok",
        }))
        override = json.dumps({
            "actor": "pr-author", "sha": "abc1234", "reason": "False positive"
        })
        policies = json.dumps({"SENTINEL": "maintainers_only", "APOLLO": "pr_author"})
        code, _out, err = run_aggregate(
            str(tmp_path),
            env_extra={
                "GH_OVERRIDE_COMMENT": override,
                "GH_HEAD_SHA": "abc1234",
                "GH_PR_AUTHOR": "pr-author",
                "GH_REVIEWER_POLICIES": policies,
            },
        )
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "FAIL"
        assert data["override"]["used"] is False
        assert "rejected by policy" in err

    def test_apollo_fail_allows_pr_author_override(self, tmp_path):
        """APOLLO (pr_author) FAIL should allow override from pr_author."""
        (tmp_path / "apollo.json").write_text(json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness",
            "verdict": "FAIL", "confidence": 0.9, "summary": "Logic issue.",
            "stats": {"critical": 1, "major": 0, "minor": 0, "info": 0},
        }))
        override = json.dumps({
            "actor": "pr-author", "sha": "abc1234", "reason": "Verified manually"
        })
        policies = json.dumps({"SENTINEL": "maintainers_only", "APOLLO": "pr_author"})
        code, _out, _err = run_aggregate(
            str(tmp_path),
            env_extra={
                "GH_OVERRIDE_COMMENT": override,
                "GH_HEAD_SHA": "abc1234",
                "GH_PR_AUTHOR": "pr-author",
                "GH_REVIEWER_POLICIES": policies,
            },
        )
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "PASS"
        assert data["override"]["used"] is True

    def test_sentinel_fail_allows_maintainer_override(self, tmp_path):
        """SENTINEL (maintainers_only) FAIL should allow override from maintainer."""
        (tmp_path / "sentinel.json").write_text(json.dumps({
            "reviewer": "SENTINEL", "perspective": "security",
            "verdict": "FAIL", "confidence": 0.9, "summary": "Security issue.",
            "stats": {"critical": 1, "major": 0, "minor": 0, "info": 0},
        }))
        override = json.dumps({
            "actor": "maintainer", "sha": "abc1234", "reason": "Verified"
        })
        policies = json.dumps({"SENTINEL": "maintainers_only"})
        code, _out, _err = run_aggregate(
            str(tmp_path),
            env_extra={
                "GH_OVERRIDE_COMMENT": override,
                "GH_HEAD_SHA": "abc1234",
                "GH_PR_AUTHOR": "other-user",
                "GH_REVIEWER_POLICIES": policies,
                "GH_OVERRIDE_ACTOR_PERMISSION": "maintain",
            },
        )
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "PASS"
        assert data["override"]["used"] is True

    def test_no_policies_env_uses_global_fallback(self, tmp_path):
        """Without GH_REVIEWER_POLICIES, falls back to GH_OVERRIDE_POLICY (backward compat)."""
        (tmp_path / "apollo.json").write_text(json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness",
            "verdict": "FAIL", "confidence": 0.9, "summary": "Issue.",
        }))
        override = json.dumps({
            "actor": "pr-author", "sha": "abc1234", "reason": "Verified"
        })
        code, _out, _err = run_aggregate(
            str(tmp_path),
            env_extra={
                "GH_OVERRIDE_COMMENT": override,
                "GH_HEAD_SHA": "abc1234",
                "GH_PR_AUTHOR": "pr-author",
                "GH_OVERRIDE_POLICY": "pr_author",
            },
        )
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "PASS"
        assert data["override"]["used"] is True

    def test_malformed_policies_json_warns_and_falls_back(self, tmp_path):
        """Malformed GH_REVIEWER_POLICIES should warn and fall back to global policy."""
        (tmp_path / "apollo.json").write_text(json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness",
            "verdict": "FAIL", "confidence": 0.9, "summary": "Issue.",
        }))
        override = json.dumps({
            "actor": "pr-author", "sha": "abc1234", "reason": "Verified"
        })
        code, _out, err = run_aggregate(
            str(tmp_path),
            env_extra={
                "GH_OVERRIDE_COMMENT": override,
                "GH_HEAD_SHA": "abc1234",
                "GH_PR_AUTHOR": "pr-author",
                "GH_OVERRIDE_POLICY": "pr_author",
                "GH_REVIEWER_POLICIES": "{not valid json}",
            },
        )
        assert code == 0
        assert "invalid GH_REVIEWER_POLICIES" in err
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        # Falls back to global pr_author, so override succeeds
        assert data["verdict"] == "PASS"
        assert data["override"]["used"] is True

    def test_non_dict_policies_warns_and_falls_back(self, tmp_path):
        """Non-dict GH_REVIEWER_POLICIES should warn and fall back to global policy."""
        (tmp_path / "apollo.json").write_text(json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness",
            "verdict": "FAIL", "confidence": 0.9, "summary": "Issue.",
        }))
        override = json.dumps({
            "actor": "pr-author", "sha": "abc1234", "reason": "Verified"
        })
        code, _out, err = run_aggregate(
            str(tmp_path),
            env_extra={
                "GH_OVERRIDE_COMMENT": override,
                "GH_HEAD_SHA": "abc1234",
                "GH_PR_AUTHOR": "pr-author",
                "GH_OVERRIDE_POLICY": "pr_author",
                "GH_REVIEWER_POLICIES": '["not","a","dict"]',
            },
        )
        assert code == 0
        assert "invalid GH_REVIEWER_POLICIES" in err
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "PASS"
        assert data["override"]["used"] is True


# ---------------------------------------------------------------------------
# Artifact validation (Issue #91)
# ---------------------------------------------------------------------------

_validate_artifact = aggregate_verdict.validate_artifact

MAX_ARTIFACT_SIZE = aggregate_verdict.MAX_ARTIFACT_SIZE


class TestValidateArtifactUnit:
    """Unit tests for validate_artifact()."""

    def test_valid_artifact(self, tmp_path):
        path = tmp_path / "good.json"
        path.write_text(json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness",
            "verdict": "PASS", "confidence": 0.9, "summary": "ok",
        }))
        data, err = _validate_artifact(path)
        assert data is not None
        assert err is None
        assert data["verdict"] == "PASS"

    def test_oversized_artifact_rejected(self, tmp_path):
        path = tmp_path / "huge.json"
        blob = {"reviewer": "X", "verdict": "PASS", "confidence": 0.9,
                "summary": "ok", "padding": "x" * (MAX_ARTIFACT_SIZE + 1)}
        path.write_text(json.dumps(blob))
        data, err = _validate_artifact(path)
        assert data is None
        assert "size" in err.lower()

    def test_invalid_json_rejected(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not valid json}")
        data, err = _validate_artifact(path)
        assert data is None
        assert "json" in err.lower()

    def test_binary_file_rejected(self, tmp_path):
        path = tmp_path / "binary.json"
        path.write_bytes(b"\x00\x01\x02\x03")
        data, err = _validate_artifact(path)
        assert data is None

    def test_missing_verdict_field(self, tmp_path):
        path = tmp_path / "no_verdict.json"
        path.write_text(json.dumps({
            "reviewer": "A", "confidence": 0.9, "summary": "ok",
        }))
        data, err = _validate_artifact(path)
        assert data is None
        assert "verdict" in err.lower()

    def test_missing_confidence_field(self, tmp_path):
        path = tmp_path / "no_conf.json"
        path.write_text(json.dumps({
            "reviewer": "A", "verdict": "PASS", "summary": "ok",
        }))
        data, err = _validate_artifact(path)
        assert data is None
        assert "confidence" in err.lower()

    def test_missing_summary_field(self, tmp_path):
        path = tmp_path / "no_summary.json"
        path.write_text(json.dumps({
            "reviewer": "A", "verdict": "PASS", "confidence": 0.9,
        }))
        data, err = _validate_artifact(path)
        assert data is None
        assert "summary" in err.lower()

    def test_invalid_verdict_value(self, tmp_path):
        path = tmp_path / "bad_verdict.json"
        path.write_text(json.dumps({
            "reviewer": "A", "verdict": "MAYBE", "confidence": 0.9, "summary": "ok",
        }))
        data, err = _validate_artifact(path)
        assert data is None
        assert "verdict" in err.lower()

    def test_non_dict_root_rejected(self, tmp_path):
        path = tmp_path / "array.json"
        path.write_text(json.dumps(["not", "a", "dict"]))
        data, err = _validate_artifact(path)
        assert data is None


class TestArtifactValidationIntegration:
    """Subprocess tests: malformed artifacts are skipped, not crashed."""

    def test_invalid_json_skipped_others_aggregated(self, tmp_path):
        """Invalid JSON artifact skipped; valid artifacts still aggregated."""
        (tmp_path / "good.json").write_text(json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness",
            "verdict": "PASS", "confidence": 0.9, "summary": "ok",
        }))
        (tmp_path / "bad.json").write_text("{not json}")
        code, out, err = run_aggregate(str(tmp_path))
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "PASS"
        assert "skipped" in err.lower()
        assert len(data.get("skipped_artifacts", [])) == 1

    def test_oversized_artifact_skipped(self, tmp_path):
        (tmp_path / "good.json").write_text(json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness",
            "verdict": "PASS", "confidence": 0.9, "summary": "ok",
        }))
        big = tmp_path / "huge.json"
        big.write_text(json.dumps({
            "reviewer": "X", "verdict": "PASS", "confidence": 0.9,
            "summary": "ok", "padding": "x" * (MAX_ARTIFACT_SIZE + 1),
        }))
        code, out, err = run_aggregate(str(tmp_path))
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "PASS"
        assert len(data.get("skipped_artifacts", [])) == 1
        assert "size" in data["skipped_artifacts"][0]["reason"].lower()

    def test_missing_required_field_skipped(self, tmp_path):
        (tmp_path / "good.json").write_text(json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness",
            "verdict": "PASS", "confidence": 0.9, "summary": "ok",
        }))
        (tmp_path / "bad.json").write_text(json.dumps({
            "reviewer": "B", "perspective": "test",
        }))
        code, out, err = run_aggregate(str(tmp_path))
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "PASS"
        assert len(data.get("skipped_artifacts", [])) == 1

    def test_all_artifacts_rejected_produces_skip(self, tmp_path):
        """When every artifact is malformed, council verdict = SKIP."""
        (tmp_path / "a.json").write_text("{bad}")
        (tmp_path / "b.json").write_text("{also bad}")
        code, out, err = run_aggregate(str(tmp_path))
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "SKIP"
        assert len(data.get("skipped_artifacts", [])) == 2

    def test_skipped_artifacts_report_filename(self, tmp_path):
        (tmp_path / "good.json").write_text(json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness",
            "verdict": "PASS", "confidence": 0.9, "summary": "ok",
        }))
        (tmp_path / "corrupt.json").write_bytes(b"\x00\x01\x02")
        code, out, err = run_aggregate(str(tmp_path))
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        skipped = data.get("skipped_artifacts", [])
        assert len(skipped) == 1
        assert "corrupt.json" in skipped[0]["file"]
# ---------------------------------------------------------------------------
# Override comment selection ordering (Issue #25)
# ---------------------------------------------------------------------------

_select_override = aggregate_verdict.select_override


class TestSelectOverrideUnit:
    """Unit tests for select_override() — first-authorized selection."""

    def test_single_authorized_override_selected(self):
        comments = json.dumps([
            {"actor": "author", "sha": "abc1234", "reason": "verified"},
        ])
        result = _select_override(
            comments, "abc1234", "pr_author", "author",
        )
        assert result is not None
        assert result.actor == "author"

    def test_first_authorized_selected_from_multiple(self):
        comments = json.dumps([
            {"actor": "author", "sha": "abc1234", "reason": "first override"},
            {"actor": "author", "sha": "abc1234", "reason": "second override"},
        ])
        result = _select_override(
            comments, "abc1234", "pr_author", "author",
        )
        assert result is not None
        assert result.reason == "first override"

    def test_unauthorized_skipped_authorized_selected(self):
        comments = json.dumps([
            {"actor": "intruder", "sha": "abc1234", "reason": "sneaky"},
            {"actor": "author", "sha": "abc1234", "reason": "legit"},
        ])
        result = _select_override(
            comments, "abc1234", "pr_author", "author",
        )
        assert result is not None
        assert result.actor == "author"
        assert result.reason == "legit"

    def test_no_authorized_overrides_returns_none(self):
        comments = json.dumps([
            {"actor": "intruder1", "sha": "abc1234", "reason": "nope"},
            {"actor": "intruder2", "sha": "abc1234", "reason": "also nope"},
        ])
        result = _select_override(
            comments, "abc1234", "pr_author", "author",
        )
        assert result is None

    def test_none_input(self):
        assert _select_override(None, "abc1234", "pr_author", "author") is None

    def test_empty_array(self):
        assert _select_override("[]", "abc1234", "pr_author", "author") is None

    def test_invalid_json(self):
        assert _select_override("{bad", "abc1234", "pr_author", "author") is None

    def test_single_object_backward_compat(self):
        """Single JSON object (not array) should still work."""
        comment = json.dumps(
            {"actor": "author", "sha": "abc1234", "reason": "verified"},
        )
        result = _select_override(
            comment, "abc1234", "pr_author", "author",
        )
        assert result is not None
        assert result.actor == "author"

    def test_write_access_policy_picks_first_authorized(self):
        comments = json.dumps([
            {"actor": "reader", "sha": "abc1234", "reason": "no perms"},
            {"actor": "admin", "sha": "abc1234", "reason": "has perms"},
        ])
        result = _select_override(
            comments, "abc1234", "write_access", "other",
            actor_permissions={"reader": "read", "admin": "admin"},
        )
        assert result is not None
        assert result.actor == "admin"
        assert result.reason == "has perms"

    def test_sha_mismatch_skipped(self):
        comments = json.dumps([
            {"actor": "author", "sha": "wrongsha", "reason": "bad sha"},
            {"actor": "author", "sha": "abc1234", "reason": "right sha"},
        ])
        result = _select_override(
            comments, "abc1234", "pr_author", "author",
        )
        assert result is not None
        assert result.reason == "right sha"

    def test_logs_selection_reason(self, capsys):
        comments = json.dumps([
            {"actor": "intruder", "sha": "abc1234", "reason": "bad"},
            {"actor": "author", "sha": "abc1234", "reason": "good"},
        ])
        _select_override(comments, "abc1234", "pr_author", "author")
        captured = capsys.readouterr()
        assert "rejected" in captured.err
        assert "authorized" in captured.err


class TestSelectOverrideIntegration:
    """Subprocess integration tests for multi-comment override selection."""

    def test_first_authorized_comment_wins(self, tmp_path):
        (tmp_path / "sentinel.json").write_text(json.dumps({
            "reviewer": "SENTINEL", "perspective": "security",
            "verdict": "FAIL", "confidence": 0.9, "summary": "Issue found.",
        }))
        comments = json.dumps([
            {"actor": "intruder", "sha": "abc1234", "reason": "sneaky override"},
            {"actor": "author", "sha": "abc1234", "reason": "legit override"},
        ])
        code, out, err = run_aggregate(
            str(tmp_path),
            env_extra={
                "GH_OVERRIDE_COMMENTS": comments,
                "GH_HEAD_SHA": "abc1234",
                "GH_PR_AUTHOR": "author",
                "GH_OVERRIDE_POLICY": "pr_author",
            },
        )
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "PASS"
        assert data["override"]["used"] is True
        assert data["override"]["actor"] == "author"
        assert "rejected" in err  # intruder rejected
        assert "authorized" in err  # author accepted

    def test_no_authorized_comments_keeps_fail(self, tmp_path):
        (tmp_path / "sentinel.json").write_text(json.dumps({
            "reviewer": "SENTINEL", "perspective": "security",
            "verdict": "FAIL", "confidence": 0.9, "summary": "Issue found.",
        }))
        comments = json.dumps([
            {"actor": "intruder1", "sha": "abc1234", "reason": "nope"},
            {"actor": "intruder2", "sha": "abc1234", "reason": "also nope"},
        ])
        code, out, err = run_aggregate(
            str(tmp_path),
            env_extra={
                "GH_OVERRIDE_COMMENTS": comments,
                "GH_HEAD_SHA": "abc1234",
                "GH_PR_AUTHOR": "author",
                "GH_OVERRIDE_POLICY": "pr_author",
            },
        )
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "FAIL"
        assert data["override"]["used"] is False

    def test_with_actor_permissions_map(self, tmp_path):
        (tmp_path / "sentinel.json").write_text(json.dumps({
            "reviewer": "SENTINEL", "perspective": "security",
            "verdict": "FAIL", "confidence": 0.9, "summary": "Issue found.",
            "stats": {"critical": 1, "major": 0, "minor": 0, "info": 0},
        }))
        comments = json.dumps([
            {"actor": "reader", "sha": "abc1234", "reason": "no perms"},
            {"actor": "maintainer", "sha": "abc1234", "reason": "has perms"},
        ])
        policies = json.dumps({"SENTINEL": "maintainers_only"})
        permissions = json.dumps({"reader": "read", "maintainer": "maintain"})
        code, out, err = run_aggregate(
            str(tmp_path),
            env_extra={
                "GH_OVERRIDE_COMMENTS": comments,
                "GH_HEAD_SHA": "abc1234",
                "GH_PR_AUTHOR": "other",
                "GH_REVIEWER_POLICIES": policies,
                "GH_OVERRIDE_ACTOR_PERMISSIONS": permissions,
            },
        )
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "PASS"
        assert data["override"]["used"] is True
        assert data["override"]["actor"] == "maintainer"

    def test_non_dict_actor_permissions_warns_and_degrades(self, tmp_path):
        """Non-dict GH_OVERRIDE_ACTOR_PERMISSIONS should warn and treat actors as unpermissioned."""
        (tmp_path / "sentinel.json").write_text(json.dumps({
            "reviewer": "SENTINEL", "perspective": "security",
            "verdict": "FAIL", "confidence": 0.9, "summary": "Issue found.",
        }))
        comments = json.dumps([
            {"actor": "author", "sha": "abc1234", "reason": "verified"},
        ])
        code, out, err = run_aggregate(
            str(tmp_path),
            env_extra={
                "GH_OVERRIDE_COMMENTS": comments,
                "GH_HEAD_SHA": "abc1234",
                "GH_PR_AUTHOR": "author",
                "GH_OVERRIDE_POLICY": "pr_author",
                "GH_OVERRIDE_ACTOR_PERMISSIONS": '["not","a","dict"]',
            },
        )
        assert code == 0
        assert "invalid GH_OVERRIDE_ACTOR_PERMISSIONS" in err
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        # pr_author policy doesn't need permissions, so override still works
        assert data["verdict"] == "PASS"
        assert data["override"]["used"] is True


# --- Parse-failure policy tests (#216) ---


class TestParseFailurePolicy:
    """Tests for parse-failure-policy handling in council aggregation."""

    @staticmethod
    def _make_fallback(reviewer: str, perspective: str) -> dict:
        return {
            "reviewer": reviewer,
            "perspective": perspective,
            "verdict": "FAIL",
            "confidence": 0.0,
            "summary": "Review output could not be parsed: no ```json block found",
        }

    def test_all_parse_failures_produce_skip(self, tmp_path):
        """When ALL reviewers are parse failures, council verdict is SKIP."""
        for name in ("apollo", "sentinel", "vulcan"):
            (tmp_path / f"{name}.json").write_text(
                json.dumps(self._make_fallback(name.upper(), name))
            )
        code, out, err = run_aggregate(str(tmp_path))
        assert code == 0
        assert "Council Verdict: SKIP" in out
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "SKIP"
        assert data["stats"]["parse_failures_reclassified"] == 3

    def test_parse_failure_with_real_fail_still_fails(self, tmp_path):
        """A real FAIL alongside parse failures still causes council FAIL."""
        (tmp_path / "apollo.json").write_text(
            json.dumps(self._make_fallback("APOLLO", "correctness"))
        )
        (tmp_path / "sentinel.json").write_text(json.dumps({
            "reviewer": "SENTINEL", "perspective": "security",
            "verdict": "FAIL", "confidence": 0.85, "summary": "Real security issue",
            "stats": {"critical": 1, "major": 0, "minor": 0, "info": 0},
        }))
        code, out, err = run_aggregate(str(tmp_path))
        assert code == 0
        assert "Council Verdict: FAIL" in out

    def test_skip_policy_silent(self, tmp_path):
        """skip policy reclassifies without warning."""
        (tmp_path / "apollo.json").write_text(
            json.dumps(self._make_fallback("APOLLO", "correctness"))
        )
        (tmp_path / "athena.json").write_text(json.dumps({
            "reviewer": "ATHENA", "perspective": "architecture",
            "verdict": "PASS", "confidence": 0.9, "summary": "ok",
        }))
        code, out, err = run_aggregate(
            str(tmp_path),
            env_extra={"PARSE_FAILURE_POLICY": "skip"},
        )
        assert code == 0
        assert "Council Verdict: PASS" in out
        assert "reclassified" not in err

    def test_warn_policy_emits_warning(self, tmp_path):
        """warn policy emits reclassification warning."""
        (tmp_path / "apollo.json").write_text(
            json.dumps(self._make_fallback("APOLLO", "correctness"))
        )
        (tmp_path / "athena.json").write_text(json.dumps({
            "reviewer": "ATHENA", "perspective": "architecture",
            "verdict": "PASS", "confidence": 0.9, "summary": "ok",
        }))
        code, out, err = run_aggregate(str(tmp_path))
        assert code == 0
        assert "Council Verdict: PASS" in out
        assert "reclassified as SKIP" in err
        assert "APOLLO" in err

    def test_stats_include_reclassified_count(self, tmp_path):
        """Stats include parse_failures_reclassified field."""
        (tmp_path / "apollo.json").write_text(
            json.dumps(self._make_fallback("APOLLO", "correctness"))
        )
        (tmp_path / "athena.json").write_text(json.dumps({
            "reviewer": "ATHENA", "perspective": "architecture",
            "verdict": "PASS", "confidence": 0.9, "summary": "ok",
        }))
        code, out, err = run_aggregate(str(tmp_path))
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["stats"]["parse_failures_reclassified"] == 1


# --- Verdict JSON robustness tests (#213) ---


class TestVerdictJsonRobustness:
    def test_council_verdict_always_has_verdict_field(self, tmp_path):
        """Council verdict JSON always has a non-null .verdict field."""
        (tmp_path / "apollo.json").write_text(json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness",
            "verdict": "PASS", "confidence": 0.9, "summary": "ok",
        }))
        code, out, err = run_aggregate(str(tmp_path))
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] in ("PASS", "WARN", "FAIL", "SKIP")

    def test_council_verdict_json_atomic_write(self, tmp_path):
        """Council verdict JSON is written atomically (no partial reads)."""
        (tmp_path / "apollo.json").write_text(json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness",
            "verdict": "PASS", "confidence": 0.9, "summary": "ok",
        }))
        code, out, err = run_aggregate(str(tmp_path))
        assert code == 0
        # File should exist and be valid JSON
        path = Path("/tmp/council-verdict.json")
        assert path.exists()
        data = json.loads(path.read_text())
        assert "verdict" in data
        # Temp file should not linger
        assert not Path("/tmp/council-verdict.json.tmp").exists()


# ---------------------------------------------------------------------------
# Branch-coverage additions (issue #198)
# Target: close remaining uncovered branches in aggregate-verdict.py
# ---------------------------------------------------------------------------

_read_json = aggregate_verdict.read_json
_is_explicit_noncritical_fail = aggregate_verdict.is_explicit_noncritical_fail
_is_timeout_skip = aggregate_verdict.is_timeout_skip
_has_critical_finding = aggregate_verdict.has_critical_finding
_generate_quality_report = aggregate_verdict.generate_quality_report


# --- read_json error paths (lines 37-42) ---

class TestReadJsonUnit:
    def test_valid_json_returns_dict(self, tmp_path):
        path = tmp_path / "ok.json"
        path.write_text('{"key": "value"}')
        assert _read_json(path) == {"key": "value"}

    def test_invalid_json_exits(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not valid json}")
        with pytest.raises(SystemExit) as exc:
            _read_json(path)
        assert exc.value.code == 2

    def test_missing_file_exits(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        with pytest.raises(SystemExit) as exc:
            _read_json(path)
        assert exc.value.code == 2


# --- validate_artifact OSError/UnicodeDecodeError paths (lines 49-50, 57-58) ---

class TestValidateArtifactErrorPaths:
    def test_nonexistent_file_stat_error(self, tmp_path):
        """File doesn't exist → OSError on stat (lines 49-50)."""
        path = tmp_path / "nonexistent.json"
        data, err = _validate_artifact(path)
        assert data is None
        assert "unable to stat" in (err or "")

    def test_invalid_utf8_bytes_read_error(self, tmp_path):
        """Invalid UTF-8 bytes → UnicodeDecodeError on read_text (lines 57-58)."""
        path = tmp_path / "invalid_utf8.json"
        path.write_bytes(b"\xff\xfe\x80\x81")
        data, err = _validate_artifact(path)
        assert data is None
        assert "unable to read" in (err or "")


# --- is_fallback_verdict TypeError/ValueError (lines 91-92) ---

class TestIsFallbackVerdictConfidenceEdges:
    def test_none_confidence_returns_false(self):
        v = {"summary": "Review output could not be parsed: err", "confidence": None}
        assert _is_fallback_verdict(v) is False

    def test_nonnumeric_confidence_returns_false(self):
        v = {"summary": "Review output could not be parsed: err", "confidence": "bad"}
        assert _is_fallback_verdict(v) is False


# --- is_timeout_skip non-string summary (line 101) ---

class TestIsTimeoutSkipUnit:
    def test_skip_non_string_summary_returns_false(self):
        assert _is_timeout_skip({"verdict": "SKIP", "summary": None}) is False

    def test_skip_with_timeout_returns_true(self):
        v = {"verdict": "SKIP", "summary": "Review skipped due to timeout after 600s."}
        assert _is_timeout_skip(v) is True

    def test_non_skip_verdict_returns_false(self):
        assert _is_timeout_skip({"verdict": "PASS", "summary": "timeout after 600s"}) is False


# --- has_critical_finding (lines 112-113, 119) ---

class TestHasCriticalFindingUnit:
    def test_none_critical_in_stats_falls_through(self):
        """TypeError in int() → pass; then checks findings (lines 112-113)."""
        v = {"stats": {"critical": None}, "findings": []}
        assert _has_critical_finding(v) is False

    def test_string_critical_in_stats_falls_through_to_findings(self):
        """ValueError → pass; critical finding in findings list (lines 112-113, 119)."""
        v = {
            "stats": {"critical": "n/a"},
            "findings": [{"severity": "critical", "file": "a.py"}],
        }
        assert _has_critical_finding(v) is True

    def test_no_stats_critical_finding_returns_true(self):
        """No stats at all; finding with severity=critical (line 119)."""
        v = {"findings": [{"severity": "critical", "category": "injection", "file": "a.py"}]}
        assert _has_critical_finding(v) is True

    def test_no_stats_no_critical_finding_returns_false(self):
        v = {"findings": [{"severity": "major"}]}
        assert _has_critical_finding(v) is False


# --- is_explicit_noncritical_fail (lines 125, 133-134, 138) ---

class TestIsExplicitNoncriticalFailUnit:
    def test_non_fail_verdict_returns_false(self):
        """line 125: short-circuit for non-FAIL verdicts."""
        assert _is_explicit_noncritical_fail({"verdict": "PASS"}) is False
        assert _is_explicit_noncritical_fail({"verdict": "WARN"}) is False
        assert _is_explicit_noncritical_fail({"verdict": "SKIP"}) is False

    def test_fail_with_none_critical_in_stats_returns_false(self):
        """TypeError in int() conversion (lines 133-134)."""
        v = {"verdict": "FAIL", "stats": {"critical": None, "major": 2}}
        assert _is_explicit_noncritical_fail(v) is False

    def test_fail_with_string_critical_in_stats_returns_false(self):
        """ValueError in int() conversion (lines 133-134)."""
        v = {"verdict": "FAIL", "stats": {"critical": "unknown", "major": 2}}
        assert _is_explicit_noncritical_fail(v) is False

    def test_fail_no_stats_with_findings_returns_true(self):
        """No stats, findings list present (line 138)."""
        v = {"verdict": "FAIL", "findings": [{"severity": "major", "file": "a.py"}]}
        assert _is_explicit_noncritical_fail(v) is True

    def test_fail_no_stats_no_findings_returns_false(self):
        """No stats, no findings → treat as blocking (conservative)."""
        v = {"verdict": "FAIL"}
        assert _is_explicit_noncritical_fail(v) is False


# --- generate_quality_report unknown verdict (lines 266->268, 295) ---

class TestGenerateQualityReportEdgeCases:
    def _council(self):
        return {"verdict": "PASS"}

    def test_unknown_verdict_type_appears_in_distribution(self):
        """Unknown verdict type falls into else branch (line 295)."""
        verdict = {
            "reviewer": "A",
            "perspective": "a",
            "verdict": "XFAIL",
            "confidence": 0.0,
            "summary": "custom",
        }
        report = _generate_quality_report([verdict], self._council(), [])
        dist = report["summary"]["verdict_distribution"]
        assert "XFAIL" in dist
        assert dist["XFAIL"] == 1

    def test_unknown_verdict_not_incremented_in_model_stats_verdicts(self):
        """Unknown verdict skips increment in nested verdicts dict (line 266->268)."""
        verdict = {
            "reviewer": "A",
            "perspective": "a",
            "verdict": "XFAIL",
            "confidence": 0.0,
            "summary": "custom",
            "model_used": "test-model",
        }
        report = _generate_quality_report([verdict], self._council(), [])
        model_stats = report["models"]["test-model"]
        assert "XFAIL" not in model_stats["verdicts"]
        assert model_stats["count"] == 1

    def test_empty_verdicts_returns_early(self):
        report = _generate_quality_report([], self._council(), [])
        assert report["summary"]["total_reviewers"] == 0
        assert "No valid verdicts" in report["errors"]


# --- main() line 379: count mismatch + fallback reviewers warning ---

def test_warns_count_mismatch_with_fallback_reviewers(tmp_path):
    """Count mismatch AND fallback verdicts: warning includes both (line 379)."""
    (tmp_path / "apollo.json").write_text(json.dumps({
        "reviewer": "APOLLO", "perspective": "correctness",
        "verdict": "PASS", "confidence": 0.9, "summary": "ok",
    }))
    (tmp_path / "sentinel.json").write_text(json.dumps({
        "reviewer": "SENTINEL", "perspective": "security",
        "verdict": "FAIL", "confidence": 0.0,
        "summary": "Review output could not be parsed: no ```json block found",
    }))
    code, _out, err = run_aggregate(
        str(tmp_path),
        env_extra={"EXPECTED_REVIEWERS": "APOLLO,ATHENA,SENTINEL"},  # 3 expected, 2 got
    )
    assert code == 0
    assert "expected 3 reviewers" in err
    assert "fallback verdicts: SENTINEL" in err
