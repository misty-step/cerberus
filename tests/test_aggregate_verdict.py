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
            env_extra={"GH_OVERRIDE_COMMENT": override, "GH_HEAD_SHA": "abc1234"}
        )
        # With override, FAIL becomes non-FAIL (exit 0)
        assert code == 0

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
            env_extra={"GH_OVERRIDE_COMMENT": override, "GH_HEAD_SHA": "abc1234"}
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
        assert "PASS" in out


class TestAggregateErrors:
    def test_missing_dir(self, tmp_path):
        code, _, err = run_aggregate(str(tmp_path / "nonexistent"))
        assert code == 2

    def test_empty_dir(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        code, _, err = run_aggregate(str(empty))
        assert code == 2
