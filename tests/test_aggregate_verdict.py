"""Tests for aggregate-verdict.py"""
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "aggregate-verdict.py"
FIXTURES = Path(__file__).parent / "fixtures" / "sample-verdicts"


def run_aggregate(verdict_dir: str, env_extra: dict | None = None) -> tuple[int, str, str]:
    """Run aggregate-verdict.py with a verdict directory."""
    env = os.environ.copy()
    env.pop("GH_OVERRIDE_COMMENT", None)
    env.pop("GH_HEAD_SHA", None)
    env.pop("GH_PR_AUTHOR", None)
    env.pop("GH_OVERRIDE_POLICY", None)
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
    def test_fail_when_any_reviewer_fails(self):
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
            "verdict": "FAIL", "summary": "Critical issue."
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
            "verdict": "FAIL", "summary": "Critical issue."
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
            v = {"reviewer": name, "perspective": name, "verdict": "PASS", "summary": "Good."}
            (tmp_path / f"{name}.json").write_text(json.dumps(v))
        code, out, _ = run_aggregate(str(tmp_path))
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "PASS"

    def test_warn_verdict_when_no_fail(self, tmp_path):
        (tmp_path / "a.json").write_text(
            json.dumps({"reviewer": "A", "perspective": "a", "verdict": "WARN", "summary": "Minor."})
        )
        (tmp_path / "b.json").write_text(
            json.dumps({"reviewer": "B", "perspective": "b", "verdict": "PASS", "summary": "Good."})
        )
        code, out, _ = run_aggregate(str(tmp_path))
        assert code == 0
        data = json.loads(Path("/tmp/council-verdict.json").read_text())
        assert data["verdict"] == "WARN"


class TestOverrideSHAValidation:
    def test_short_sha_rejected(self, tmp_path):
        fail_verdict = {
            "reviewer": "SENTINEL", "perspective": "security",
            "verdict": "FAIL", "summary": "Issue."
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
            "verdict": "FAIL", "summary": "Issue."
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
        assert data["verdict"] != "FAIL"  # Override accepted


class TestOverrideActorAuthorization:
    def test_override_rejected_when_actor_not_pr_author(self, tmp_path):
        fail_verdict = {
            "reviewer": "SENTINEL", "perspective": "security",
            "verdict": "FAIL", "summary": "Issue."
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
            "verdict": "FAIL", "summary": "Issue."
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
            "verdict": "FAIL", "summary": "Issue."
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
            "verdict": "FAIL", "summary": "Issue."
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
            "verdict": "FAIL", "summary": "Issue."
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
            "verdict": "FAIL", "summary": "Issue."
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
            "verdict": "FAIL", "summary": "Issue."
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
            "verdict": "FAIL", "summary": "Issue."
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
