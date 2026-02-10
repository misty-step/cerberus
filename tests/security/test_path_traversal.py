"""Verify path traversal via perspective argument is rejected.

The perspective parameter flows into file paths.  Malicious values like
"../../etc/passwd" or "foo/bar" must be rejected before any file I/O.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
RUN_REVIEWER = REPO_ROOT / "scripts" / "run-reviewer.sh"


def _base_env(diff_file: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["CERBERUS_ROOT"] = str(REPO_ROOT)
    env["GH_DIFF_FILE"] = str(diff_file)
    env["OPENROUTER_API_KEY"] = "test-key-not-real"
    env["REVIEW_TIMEOUT"] = "5"
    return env


@pytest.mark.parametrize(
    "perspective",
    [
        "../etc/passwd",
        "../../secrets",
        "foo/bar",
        "security/../../../etc/shadow",
    ],
)
def test_path_traversal_in_perspective_rejected(tmp_path: Path, perspective: str) -> None:
    diff_file = tmp_path / "diff.patch"
    diff_file.write_text("diff --git a/f b/f\n+x\n")

    result = subprocess.run(
        [str(RUN_REVIEWER), perspective],
        env=_base_env(diff_file),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    # Should fail with either "missing agent file" (no such agent) or
    # "invalid perspective" (caught by the traversal guard).
    assert (
        "missing agent file" in result.stderr
        or "invalid perspective" in result.stderr
    )
