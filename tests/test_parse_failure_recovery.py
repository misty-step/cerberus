"""Tests for parse-failure retry logic in run-reviewer.sh and parse-review.py"""

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
RUN_REVIEWER = REPO_ROOT / "scripts" / "run-reviewer.sh"
PARSE_REVIEW = REPO_ROOT / "scripts" / "parse-review.py"


def make_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def make_env(bin_dir: Path, diff_file: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["CERBERUS_ROOT"] = str(REPO_ROOT)
    env["GH_DIFF_FILE"] = str(diff_file)
    env["OPENROUTER_API_KEY"] = "test-key-not-real"
    env["OPENCODE_MAX_STEPS"] = "5"
    env["REVIEW_TIMEOUT"] = "30"
    return env


def write_simple_diff(path: Path) -> None:
    path.write_text("diff --git a/app.py b/app.py\n+print('hello')\n")


def cleanup_parse_failure_metadata(perspective: str = "security") -> None:
    """Clean up parse-failure metadata files."""
    for suffix in ("parse-failure-models.txt", "parse-failure-retries.txt"):
        Path(f"/tmp/{perspective}-{suffix}").unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def cleanup_tmp_outputs() -> None:
    """Keep /tmp artifacts from one test from leaking into others."""
    suffixes = (
        "parse-input", "output.txt", "stderr.log", "exitcode", "review.md",
        "timeout-marker.txt", "fast-path-prompt.md", "fast-path-output.txt",
        "fast-path-stderr.log", "model-used", "primary-model",
        "parse-failure-models.txt", "parse-failure-retries.txt",
    )
    perspectives = ("correctness", "architecture", "security", "performance", "maintainability")
    for perspective in perspectives:
        for suffix in suffixes:
            Path(f"/tmp/{perspective}-{suffix}").unlink(missing_ok=True)
    yield
    for perspective in perspectives:
        for suffix in suffixes:
            Path(f"/tmp/{perspective}-{suffix}").unlink(missing_ok=True)


class TestParseFailureRecovery:
    """Tests for parse-failure retry logic in run-reviewer.sh"""

    def test_valid_json_skips_recovery(self, tmp_path: Path) -> None:
        """If first attempt produces valid JSON, no recovery needed."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()

        # opencode that produces valid JSON
        make_executable(
            bin_dir / "opencode",
            (
                "#!/usr/bin/env bash\n"
                "cat <<'REVIEW'\n"
                "```json\n"
                '{"reviewer":"STUB","perspective":"security","verdict":"PASS",'
                '"confidence":0.95,"summary":"Valid output",'
                '"findings":[],"stats":{"files_reviewed":1,"files_with_issues":0,'
                '"critical":0,"major":0,"minor":0,"info":0}}\n'
                "```\n"
                "REVIEW\n"
            ),
        )

        diff_file = tmp_path / "diff.patch"
        write_simple_diff(diff_file)

        result = subprocess.run(
            [str(RUN_REVIEWER), "security"],
            env=make_env(bin_dir, diff_file),
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0
        # Should NOT have parse-failure metadata files
        assert not Path("/tmp/security-parse-failure-models.txt").exists()
        assert not Path("/tmp/security-parse-failure-retries.txt").exists()

    def test_invalid_json_triggers_recovery(self, tmp_path: Path) -> None:
        """If output has no JSON block, recovery retries are attempted."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()

        # opencode that produces invalid output (no JSON)
        opencode_script = tmp_path / "opencode_script.sh"
        make_executable(
            opencode_script,
            (
                "#!/usr/bin/env bash\n"
                'COUNT_FILE="' + str(tmp_path / 'count') + '"\n'
                'if [[ ! -f "$COUNT_FILE" ]]; then echo 0 > "$COUNT_FILE"; fi\n'
                'COUNT=$(cat "$COUNT_FILE")\n'
                'COUNT=$((COUNT + 1))\n'
                'echo "$COUNT" > "$COUNT_FILE"\n'
                'if [[ "$COUNT" -lt 3 ]]; then\n'
                '  echo "Invalid output without JSON"\n'
                'else\n'
                '  cat <<\'REVIEW\'\n'
                "```json\n"
                '{"reviewer":"STUB","perspective":"security","verdict":"PASS",'
                '"confidence":0.95,"summary":"Recovered",'
                '"findings":[],"stats":{"files_reviewed":1,"files_with_issues":0,'
                '"critical":0,"major":0,"minor":0,"info":0}}\n'
                "```\n"
                "REVIEW\n"
                "fi\n"
            ),
        )

        # Create wrapper that uses the script
        make_executable(bin_dir / "opencode", f"#!/usr/bin/env bash\nexec '{opencode_script}'\n")

        diff_file = tmp_path / "diff.patch"
        write_simple_diff(diff_file)

        result = subprocess.run(
            [str(RUN_REVIEWER), "security"],
            env=make_env(bin_dir, diff_file),
            capture_output=True,
            text=True,
            timeout=60,
        )

        # Script completes successfully; recovery was attempted
        assert result.returncode == 0
        assert "Parse failure detected" in result.stdout
        assert "Parse recovery retry" in result.stdout

    def test_recovery_exhaustion_writes_metadata(self, tmp_path: Path) -> None:
        """If all recovery attempts fail, metadata files are written."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()

        # opencode that always produces invalid output
        make_executable(
            bin_dir / "opencode",
            (
                "#!/usr/bin/env bash\n"
                "echo 'Invalid output without JSON block'\n"
            ),
        )

        diff_file = tmp_path / "diff.patch"
        write_simple_diff(diff_file)

        result = subprocess.run(
            [str(RUN_REVIEWER), "security"],
            env=make_env(bin_dir, diff_file),
            capture_output=True,
            text=True,
            timeout=60,
        )

        # Script succeeds but leaves metadata for parse-review.py
        assert result.returncode == 0
        assert Path("/tmp/security-parse-failure-models.txt").exists()
        assert Path("/tmp/security-parse-failure-retries.txt").exists()

        # Verify content
        models = Path("/tmp/security-parse-failure-models.txt").read_text().splitlines()
        retries = int(Path("/tmp/security-parse-failure-retries.txt").read_text().strip())

        assert len(models) >= 1  # At least primary model attempted
        assert retries >= 1  # At least one retry attempted


class TestParseReviewMetadata:
    """Tests for parse-review.py handling of retry metadata"""

    def run_parse(self, input_text: str, env_extra: dict | None = None, perspective: str = "security") -> tuple[int, str, str]:
        """Run parse-review.py with input text."""
        env = os.environ.copy()
        env.pop("REVIEWER_NAME", None)
        env["PERSPECTIVE"] = perspective
        if env_extra:
            env.update(env_extra)
        result = subprocess.run(
            [sys.executable, str(PARSE_REVIEW)],
            input=input_text,
            capture_output=True,
            text=True,
            env=env,
        )
        return result.returncode, result.stdout, result.stderr

    def test_skip_includes_retry_metadata(self, tmp_path: Path) -> None:
        """SKIP verdict includes parse-failure retry metadata when available."""
        perspective = "security"

        # Create parse-failure metadata files
        models_file = Path(f"/tmp/{perspective}-parse-failure-models.txt")
        retries_file = Path(f"/tmp/{perspective}-parse-failure-retries.txt")

        models_file.write_text("model-a\nmodel-b\n")
        retries_file.write_text("2")

        try:
            code, out, _ = self.run_parse(
                "Just some text without JSON",
                env_extra={"REVIEWER_NAME": "SENTINEL"},
                perspective=perspective,
            )

            assert code == 0
            data = json.loads(out)
            assert data["verdict"] == "SKIP"
            assert data["reviewer"] == "SENTINEL"
            # Summary should include retry info
            assert "parse-recovery retries" in data["summary"]
            assert "2" in data["summary"]  # retry count
            assert "model-a" in data["summary"] or "Models tried" in data["summary"]
        finally:
            cleanup_parse_failure_metadata(perspective)

    def test_skip_without_metadata(self, tmp_path: Path) -> None:
        """SKIP verdict works normally when no retry metadata exists."""
        perspective = "security"
        cleanup_parse_failure_metadata(perspective)

        code, out, _ = self.run_parse(
            "Just some text without JSON",
            env_extra={"REVIEWER_NAME": "SENTINEL"},
            perspective=perspective,
        )

        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        # Should not have retry info in summary
        assert "parse-recovery" not in data["summary"]

    def test_scratchpad_parsed_despite_metadata(self, tmp_path: Path) -> None:
        """Scratchpad input is parsed normally even with retry metadata."""
        perspective = "correctness"

        # Create metadata files (should be ignored for valid scratchpad)
        models_file = Path(f"/tmp/{perspective}-parse-failure-models.txt")
        retries_file = Path(f"/tmp/{perspective}-parse-failure-retries.txt")
        models_file.write_text("model-x\n")
        retries_file.write_text("3")

        try:
            # Valid scratchpad format (no JSON but has verdict header)
            scratchpad = "## Verdict:\nPASS\n\nSome analysis here"

            code, out, _ = self.run_parse(
                scratchpad,
                env_extra={"REVIEWER_NAME": "APOLLO"},
                perspective=perspective,
            )

            assert code == 0
            data = json.loads(out)
            # Should parse as partial review, not SKIP
            assert data["verdict"] == "PASS"
        finally:
            cleanup_parse_failure_metadata(perspective)


class TestHasValidJsonBlock:
    """Tests for the has_valid_json_block helper function in run-reviewer.sh"""

    def test_detects_json_block(self, tmp_path: Path) -> None:
        """Function correctly identifies valid JSON blocks."""
        # This is tested indirectly through run-reviewer.sh behavior
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()

        # First call: invalid, second call: valid JSON
        opencode_script = tmp_path / "opencode.sh"
        make_executable(
            opencode_script,
            (
                "#!/usr/bin/env bash\n"
                'COUNT_FILE="' + str(tmp_path / 'count') + '"\n'
                'if [[ ! -f "$COUNT_FILE" ]]; then echo 0 > "$COUNT_FILE"; fi\n'
                'COUNT=$(cat "$COUNT_FILE")\n'
                'COUNT=$((COUNT + 1))\n'
                'echo "$COUNT" > "$COUNT_FILE"\n'
                'if [[ "$COUNT" == "1" ]]; then\n'
                '  echo "No JSON here"\n'
                'else\n'
                '  echo "```json"\n'
                '  echo \'{\\"verdict\\": \\"PASS\\"}\'\n'
                '  echo "```"\n'
                "fi\n"
            ),
        )
        make_executable(bin_dir / "opencode", f"#!/usr/bin/env bash\nexec bash '{opencode_script}'\n")

        diff_file = tmp_path / "diff.patch"
        write_simple_diff(diff_file)

        result = subprocess.run(
            [str(RUN_REVIEWER), "security"],
            env=make_env(bin_dir, diff_file),
            capture_output=True,
            text=True,
            timeout=60,
        )

        # Should succeed after recovery
        assert result.returncode == 0
        # Should mention parse recovery in output
        assert "Parse recovery" in result.stdout or "parse failure" in result.stdout.lower() or "recovery" in result.stdout
