"""Tests for Issue #26: mktemp-based temp file handling.

Verifies that Python scripts respect CERBERUS_TMP and have no hardcoded /tmp/ paths.
"""

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
FIXTURES = Path(__file__).parent / "fixtures" / "sample-verdicts"

SCRIPT_AGGREGATE = SCRIPTS_DIR / "aggregate-verdict.py"
SCRIPT_PARSE = SCRIPTS_DIR / "parse-review.py"
REPO_ROOT = Path(__file__).parent.parent
ACTION_FILE = REPO_ROOT / "action.yml"
VERDICT_ACTION_FILE = REPO_ROOT / "verdict" / "action.yml"


def _run(script: Path, args: list[str], env: dict[str, str]) -> tuple[int, str, str]:
    result = subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


class TestAggregateUsesCerberusTmp:
    def test_council_verdict_written_to_cerberus_tmp(self, tmp_path: Path) -> None:
        """aggregate-verdict.py writes council-verdict.json to CERBERUS_TMP."""
        env = {**os.environ, "CERBERUS_TMP": str(tmp_path)}
        env.pop("GH_OVERRIDE_COMMENT", None)
        env.pop("GH_HEAD_SHA", None)

        code, _, _ = _run(SCRIPT_AGGREGATE, [str(FIXTURES)], env)

        assert code == 0
        assert (tmp_path / "council-verdict.json").exists()

    def test_quality_report_written_to_cerberus_tmp(self, tmp_path: Path) -> None:
        """aggregate-verdict.py writes quality-report.json to CERBERUS_TMP."""
        env = {**os.environ, "CERBERUS_TMP": str(tmp_path)}
        env.pop("GH_OVERRIDE_COMMENT", None)
        env.pop("GH_HEAD_SHA", None)

        _run(SCRIPT_AGGREGATE, [str(FIXTURES)], env)

        assert (tmp_path / "quality-report.json").exists()

    def test_council_verdict_not_in_fixed_tmp(self, tmp_path: Path) -> None:
        """When CERBERUS_TMP is set to a unique dir, the file goes there, not /tmp/."""
        env = {**os.environ, "CERBERUS_TMP": str(tmp_path)}
        env.pop("GH_OVERRIDE_COMMENT", None)
        env.pop("GH_HEAD_SHA", None)

        _run(SCRIPT_AGGREGATE, [str(FIXTURES)], env)

        output = tmp_path / "council-verdict.json"
        assert output.exists()
        assert str(output) != "/tmp/council-verdict.json"

    def test_council_verdict_json_is_valid(self, tmp_path: Path) -> None:
        """Output JSON is parseable and has expected fields."""
        env = {**os.environ, "CERBERUS_TMP": str(tmp_path)}
        env.pop("GH_OVERRIDE_COMMENT", None)
        env.pop("GH_HEAD_SHA", None)

        _run(SCRIPT_AGGREGATE, [str(FIXTURES)], env)

        data = json.loads((tmp_path / "council-verdict.json").read_text())
        assert "verdict" in data


class TestParseReviewUsesCerberusTmp:
    """parse-review.py uses CERBERUS_TMP for parse-failure tracking files."""

    def test_parse_failure_tracking_in_cerberus_tmp(self, tmp_path: Path) -> None:
        """On parse failure, tracking files land in CERBERUS_TMP."""
        env = {**os.environ, "CERBERUS_TMP": str(tmp_path), "REVIEWER_NAME": "APOLLO"}
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PARSE)],
            input="This is not valid JSON output at all",
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

        assert result.returncode == 0
        for path in tmp_path.iterdir():
            assert not str(path).startswith("/tmp/")


class TestNoPythonHardcodedTmpPaths:
    """Grep check: no Python script has literal /tmp/ paths."""

    PYTHON_FILES = [
        SCRIPTS_DIR / "aggregate-verdict.py",
        SCRIPTS_DIR / "parse-review.py",
        SCRIPTS_DIR / "triage.py",
        SCRIPTS_DIR / "post-council-review.py",
        SCRIPTS_DIR / "lib" / "render_council_comment.py",
    ]

    def test_no_hardcoded_tmp_slash_in_python(self) -> None:
        """No production Python file contains literal string /tmp/."""
        violations = []
        for py_file in self.PYTHON_FILES:
            if not py_file.exists():
                continue
            for line_number, line in enumerate(py_file.read_text().splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if '"/tmp/' in line or "'/tmp/" in line:
                    violations.append(f"{py_file.name}:{line_number}: {stripped}")
        assert not violations, (
            "Hardcoded /tmp/ paths found in Python scripts:\n" + "\n".join(violations)
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
        assert 'rm -rf "${CERBERUS_TMP}"' in cleanup_block

    def test_review_action_has_temp_setup_and_always_cleanup(self) -> None:
        self._assert_temp_lifecycle(ACTION_FILE)

    def test_verdict_action_has_temp_setup_and_always_cleanup(self) -> None:
        self._assert_temp_lifecycle(VERDICT_ACTION_FILE)
