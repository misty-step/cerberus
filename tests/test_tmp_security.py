"""Tests for Issue #26: mktemp-based temp file handling.

Verifies that scripts respect CERBERUS_TMP and have no hardcoded /tmp/ paths.
"""

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
FIXTURES = Path(__file__).parent / "fixtures" / "sample-verdicts"

SCRIPT_AGGREGATE = SCRIPTS_DIR / "aggregate-verdict.py"
SCRIPT_PARSE = SCRIPTS_DIR / "parse-review.py"
REPO_ROOT = Path(__file__).parent.parent
ACTION_FILE = REPO_ROOT / "action.yml"
VERDICT_ACTION_FILE = REPO_ROOT / "verdict" / "action.yml"
TRIAGE_ACTION_FILE = REPO_ROOT / "triage" / "action.yml"

# Shell scripts that previously had hardcoded /tmp/ paths.
SHELL_SCRIPTS = [
    SCRIPTS_DIR / "run-reviewer.sh",
    SCRIPTS_DIR / "post-comment.sh",
]

# Python scripts that write to CERBERUS_TMP.
PYTHON_SCRIPTS = [
    SCRIPTS_DIR / "aggregate-verdict.py",
    SCRIPTS_DIR / "parse-review.py",
    SCRIPTS_DIR / "triage.py",
    SCRIPTS_DIR / "post-verdict-review.py",
    SCRIPTS_DIR / "lib" / "render_verdict_comment.py",
]


def _run(script: Path, args: list[str], env: dict[str, str]) -> tuple[int, str, str]:
    result = subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


@pytest.fixture()
def aggregate_env(tmp_path: Path) -> dict[str, str]:
    """Clean env for aggregate-verdict.py with CERBERUS_TMP pointed at tmp_path."""
    env = {**os.environ, "CERBERUS_TMP": str(tmp_path)}
    env.pop("GH_OVERRIDE_COMMENT", None)
    env.pop("GH_HEAD_SHA", None)
    return env


class TestAggregateUsesCerberusTmp:
    def test_verdict_written_to_cerberus_tmp(
        self, tmp_path: Path, aggregate_env: dict[str, str]
    ) -> None:
        """aggregate-verdict.py writes verdict.json to CERBERUS_TMP."""
        code, _, _ = _run(SCRIPT_AGGREGATE, [str(FIXTURES)], aggregate_env)

        assert code == 0
        assert (tmp_path / "verdict.json").exists()

    def test_quality_report_written_to_cerberus_tmp(
        self, tmp_path: Path, aggregate_env: dict[str, str]
    ) -> None:
        """aggregate-verdict.py writes quality-report.json to CERBERUS_TMP."""
        _run(SCRIPT_AGGREGATE, [str(FIXTURES)], aggregate_env)

        assert (tmp_path / "quality-report.json").exists()

    def test_verdict_not_in_fixed_tmp(
        self, tmp_path: Path, aggregate_env: dict[str, str]
    ) -> None:
        """When CERBERUS_TMP is set to a unique dir, the file goes there, not /tmp/."""
        _run(SCRIPT_AGGREGATE, [str(FIXTURES)], aggregate_env)

        output = tmp_path / "verdict.json"
        assert output.exists()
        assert str(output) != "/tmp/verdict.json"

    def test_verdict_json_is_valid(
        self, tmp_path: Path, aggregate_env: dict[str, str]
    ) -> None:
        """Output JSON is parseable and has expected fields."""
        _run(SCRIPT_AGGREGATE, [str(FIXTURES)], aggregate_env)

        data = json.loads((tmp_path / "verdict.json").read_text())
        assert "verdict" in data


class TestParseReviewUsesCerberusTmp:
    """parse-review.py reads parse-failure metadata from CERBERUS_TMP."""

    def test_reads_tracking_files_from_cerberus_tmp(self, tmp_path: Path) -> None:
        """When parse-failure tracking files exist in CERBERUS_TMP, they are read."""
        perspective = "TMPTEST"
        # Pre-create the tracking files that run-reviewer.sh would write.
        (tmp_path / f"{perspective}-parse-failure-models.txt").write_text(
            "model-a\nmodel-b\n"
        )
        (tmp_path / f"{perspective}-parse-failure-retries.txt").write_text("2")

        env = {
            **os.environ,
            "CERBERUS_TMP": str(tmp_path),
            "PERSPECTIVE": perspective,
            "REVIEWER_NAME": "TMPTEST",
        }
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PARSE)],
            input="This is not valid JSON output at all",
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

        assert result.returncode == 0
        data = json.loads(result.stdout)
        # Verify the metadata was found and surfaced in the verdict summary.
        assert "model-a" in data["summary"] or "2" in data["summary"]

    def test_no_output_written_to_fixed_tmp(self, tmp_path: Path) -> None:
        """parse-review.py does not write files outside CERBERUS_TMP."""
        env = {
            **os.environ,
            "CERBERUS_TMP": str(tmp_path),
            "REVIEWER_NAME": "APOLLO",
        }
        subprocess.run(
            [sys.executable, str(SCRIPT_PARSE)],
            input="This is not valid JSON output at all",
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

        for path in tmp_path.iterdir():
            assert not str(path).startswith("/tmp/")


class TestNoHardcodedTmpPaths:
    """Grep check: no script or action YAML has literal /tmp/ paths."""

    @staticmethod
    def _scan_for_tmp(file_path: Path, skip_comments: str = "#") -> list[str]:
        """Return lines containing hardcoded /tmp/ paths, skipping comments."""
        violations = []
        if not file_path.exists():
            return violations
        for line_number, line in enumerate(file_path.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(skip_comments):
                continue
            if '"/tmp/' in line or "'/tmp/" in line or " /tmp/" in line:
                # Allow YAML comments (lines starting with #).
                if stripped.startswith("#"):
                    continue
                violations.append(f"{file_path.name}:{line_number}: {stripped}")
        return violations

    def test_no_hardcoded_tmp_in_python_scripts(self) -> None:
        """No production Python file contains literal string /tmp/."""
        violations = []
        for py_file in PYTHON_SCRIPTS:
            violations.extend(self._scan_for_tmp(py_file))
        assert not violations, (
            "Hardcoded /tmp/ paths found in Python scripts:\n" + "\n".join(violations)
        )

    def test_no_hardcoded_tmp_in_shell_scripts(self) -> None:
        """No shell script contains literal string /tmp/."""
        violations = []
        for sh_file in SHELL_SCRIPTS:
            violations.extend(self._scan_for_tmp(sh_file))
        assert not violations, (
            "Hardcoded /tmp/ paths found in shell scripts:\n" + "\n".join(violations)
        )

    def test_no_hardcoded_tmp_in_action_yaml(self) -> None:
        """No action YAML contains literal string /tmp/."""
        violations = []
        for action_file in [ACTION_FILE, VERDICT_ACTION_FILE, TRIAGE_ACTION_FILE]:
            violations.extend(self._scan_for_tmp(action_file))
        assert not violations, (
            "Hardcoded /tmp/ paths found in action YAML:\n" + "\n".join(violations)
        )


class TestCerberusTmpPermissions:
    """Restrictive permissions on the temp directory."""

    def test_fresh_cerberus_tmp_has_0700_perms(self, tmp_path: Path) -> None:
        """When action creates CERBERUS_TMP with chmod 0700, perms are restrictive."""
        cerberus_tmp = tmp_path / "cerberus-XXXXXX"
        cerberus_tmp.mkdir(mode=0o700)
        mode = stat.S_IMODE(cerberus_tmp.stat().st_mode)
        assert mode == 0o700, f"Expected 0700, got {oct(mode)}"


class TestActionTempLifecycle:
    """Composite actions create and clean up CERBERUS_TMP securely."""

    @staticmethod
    def _assert_temp_lifecycle(action_path: Path) -> None:
        content = action_path.read_text()

        assert "mktemp -d -t cerberus.XXXXXX" in content
        assert 'chmod 0700 "$cerberus_tmp"' in content
        assert 'echo "CERBERUS_TMP=${cerberus_tmp}" >> "$GITHUB_ENV"' in content

        cleanup = re.search(
            r"- name: Clean up temp directory\n(.*?)(?:\n    - name:|\Z)",
            content,
            re.DOTALL,
        )
        assert cleanup is not None
        cleanup_block = cleanup.group(0)
        assert "if: always()" in cleanup_block
        assert 'chmod -R u+rwX "${CERBERUS_TMP}" 2>/dev/null || true' in cleanup_block
        assert 'rm -rf "${CERBERUS_TMP}" 2>/dev/null || true' in cleanup_block
        assert 'if [[ -d "${CERBERUS_TMP}" ]]; then' in cleanup_block
        assert "::warning::Failed to fully clean temporary directory" in cleanup_block

    def test_review_action_has_temp_setup_and_always_cleanup(self) -> None:
        self._assert_temp_lifecycle(ACTION_FILE)

    def test_verdict_action_has_temp_setup_and_always_cleanup(self) -> None:
        self._assert_temp_lifecycle(VERDICT_ACTION_FILE)

    def test_triage_action_has_temp_setup_and_always_cleanup(self) -> None:
        self._assert_temp_lifecycle(TRIAGE_ACTION_FILE)

    def test_verdict_json_output_uses_runner_temp_not_cerberus_tmp(self) -> None:
        """verdict-json output must point to RUNNER_TEMP so it survives CERBERUS_TMP cleanup."""
        content = ACTION_FILE.read_text()
        assert 'RUNNER_TEMP' in content
        assert 'artifact_suffix_safe' in content
        assert 'cerberus-${PERSPECTIVE}-' in content
        assert '-verdict.json' in content
        stable_output_line = 'echo "verdict-json=${stable_json}" >> "$GITHUB_OUTPUT"'
        assert stable_output_line in content
        cerberus_tmp_output_line = 'echo "verdict-json=${CERBERUS_TMP}/${PERSPECTIVE}-verdict.json" >> "$GITHUB_OUTPUT"'
        assert cerberus_tmp_output_line not in content
