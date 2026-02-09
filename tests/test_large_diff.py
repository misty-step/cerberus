"""Regression tests for issue #51: Argument list too long on large PR diffs.

Verifies that run-reviewer.sh passes the prompt via command argument
without exceeding ARG_MAX limits on diffs >2 MB.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
RUN_REVIEWER = SCRIPTS_DIR / "run-reviewer.sh"


@pytest.fixture()
def stub_opencode(tmp_path):
    """Create a stub opencode binary that emits valid review JSON."""
    stub = tmp_path / "opencode"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "cat <<'REVIEW'\n"
        "```json\n"
        '{"reviewer":"STUB","perspective":"correctness","verdict":"PASS",'
        '"confidence":0.95,"summary":"Stub review",'
        '"findings":[],"stats":{"files_reviewed":1,"files_with_issues":0,'
        '"critical":0,"major":0,"minor":0,"info":0}}\n'
        "```\n"
        "REVIEW\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return stub


@pytest.fixture()
def large_diff(tmp_path):
    """Generate a 3 MB diff file (exceeds typical ARG_MAX of ~2 MB)."""
    diff_file = tmp_path / "large.diff"
    line = "diff --git a/big.py b/big.py\n+" + "x" * 200 + "\n"
    target = 3 * 1024 * 1024
    with open(diff_file, "w") as f:
        written = 0
        while written < target:
            f.write(line)
            written += len(line)
    return diff_file


@pytest.fixture()
def reviewer_env(tmp_path, stub_opencode, large_diff):
    """Set up environment for run-reviewer.sh with stub opencode."""
    env = os.environ.copy()
    env["PATH"] = str(stub_opencode.parent) + ":" + env.get("PATH", "")
    env["CERBERUS_ROOT"] = str(REPO_ROOT)
    env["GH_DIFF_FILE"] = str(large_diff)
    env["OPENROUTER_API_KEY"] = "test-key-not-real"
    env["OPENCODE_MAX_STEPS"] = "5"
    env["REVIEW_TIMEOUT"] = "30"
    return env


class TestLargeDiffStdin:
    """Functional tests: run-reviewer.sh handles large diffs."""

    def test_large_diff_does_not_hit_arg_max(self, reviewer_env):
        """A 3 MB diff must not cause 'Argument list too long' (exit 126)."""
        result = subprocess.run(
            [str(RUN_REVIEWER), "correctness"],
            env=reviewer_env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 126, (
            f"ARG_MAX exceeded (exit 126).\nstderr: {result.stderr[:500]}"
        )
        assert result.returncode == 0, (
            f"Unexpected exit {result.returncode}.\nstderr: {result.stderr[:500]}"
        )

    def test_output_contains_json_block(self, reviewer_env):
        """run-reviewer.sh should capture the stub's JSON output."""
        result = subprocess.run(
            [str(RUN_REVIEWER), "correctness"],
            env=reviewer_env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0
        # run-reviewer.sh tails the parse input; check it found a JSON block
        assert "```json" in result.stdout, (
            f"Expected JSON block in output.\nstdout tail: {result.stdout[-500:]}"
        )

    def test_parse_input_file_has_json(self, reviewer_env):
        """The parse-input file should reference a file with valid JSON."""
        subprocess.run(
            [str(RUN_REVIEWER), "correctness"],
            env=reviewer_env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        parse_input_ref = Path("/tmp/correctness-parse-input")
        assert parse_input_ref.exists(), "parse-input reference file missing"
        parse_file = Path(parse_input_ref.read_text().strip())
        assert parse_file.exists(), f"Parse input file {parse_file} missing"
        content = parse_file.read_text()
        assert "```json" in content, "Parse input file has no JSON block"
        assert '"verdict"' in content, "Parse input file missing verdict field"


class TestNoCommandSubstitution:
    """Static checks: prompt handling in run-reviewer.sh."""

    def test_opencode_run_present(self):
        """run-reviewer.sh must invoke opencode run."""
        source = RUN_REVIEWER.read_text()
        assert "opencode run" in source, (
            "run-reviewer.sh does not invoke opencode run"
        )

    def test_review_prompt_referenced(self):
        """run-reviewer.sh should reference the review prompt file."""
        source = RUN_REVIEWER.read_text()
        assert "review-prompt.md" in source, (
            "Expected reference to review-prompt.md"
        )
