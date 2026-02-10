"""Tests for prompt construction and agent config consistency.

With the minimal context approach, the diff is NOT injected inline into the
prompt. Instead the prompt references the diff file path and the agent reads
it directly. These tests verify:
- The prompt references the diff file path (not inline content)
- The prompt does NOT contain raw diff content
- Agent configs all have the test-only rule
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
RUN_REVIEWER = REPO_ROOT / "scripts" / "run-reviewer.sh"
AGENTS_DIR = REPO_ROOT / ".opencode" / "agents"


def _make_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _build_diff_hunk(path: str, added_line: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        "index 1111111..2222222 100644\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -0,0 +1 @@\n"
        f"+{added_line}\n"
    )


@pytest.fixture()
def stub_opencode(tmp_path: Path) -> tuple[Path, Path]:
    """Stub opencode and capture stdin prompt for assertions."""
    stub = tmp_path / "opencode"
    prompt_capture = tmp_path / "captured-prompt.md"
    _make_executable(
        stub,
        (
            "#!/usr/bin/env bash\n"
            "cat > \"${OPENCODE_CAPTURE_PATH}\"\n"
            "cat <<'REVIEW'\n"
            "```json\n"
            '{"reviewer":"STUB","perspective":"correctness","verdict":"PASS",'
            '"confidence":0.95,"summary":"Stub review",'
            '"findings":[],"stats":{"files_reviewed":1,"files_with_issues":0,'
            '"critical":0,"major":0,"minor":0,"info":0}}\n'
            "```\n"
            "REVIEW\n"
        ),
    )
    return stub, prompt_capture


@pytest.fixture()
def reviewer_env(stub_opencode: tuple[Path, Path]) -> dict[str, str]:
    """Shared environment for run-reviewer.sh execution."""
    stub, prompt_capture = stub_opencode
    env = os.environ.copy()
    env["PATH"] = f"{stub.parent}:{env.get('PATH', '')}"
    env["CERBERUS_ROOT"] = str(REPO_ROOT)
    env["OPENROUTER_API_KEY"] = "test-key-not-real"
    env["OPENCODE_MAX_STEPS"] = "5"
    env["REVIEW_TIMEOUT"] = "30"
    env["OPENCODE_CAPTURE_PATH"] = str(prompt_capture)
    return env


def _run_reviewer(
    diff_text: str, tmp_path: Path, reviewer_env: dict[str, str]
) -> tuple[subprocess.CompletedProcess[str], str, Path]:
    diff_file = tmp_path / "pr.diff"
    diff_file.write_text(diff_text)
    env = reviewer_env.copy()
    env["GH_DIFF_FILE"] = str(diff_file)

    result = subprocess.run(
        [str(RUN_REVIEWER), "correctness"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"run-reviewer.sh failed ({result.returncode}).\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )

    prompt_capture = Path(env["OPENCODE_CAPTURE_PATH"])
    assert prompt_capture.exists(), "Stub opencode did not capture prompt input"
    prompt_text = prompt_capture.read_text()
    return result, prompt_text, diff_file


def test_prompt_references_diff_file_path(
    tmp_path: Path, reviewer_env: dict[str, str]
) -> None:
    """The prompt should contain the diff FILE PATH, not inline diff content."""
    diff_text = _build_diff_hunk("src/app.py", "print('app')")
    _, prompt_text, diff_file = _run_reviewer(diff_text, tmp_path, reviewer_env)

    # Prompt references the diff file path
    assert str(diff_file) in prompt_text


def test_prompt_does_not_contain_inline_diff(
    tmp_path: Path, reviewer_env: dict[str, str]
) -> None:
    """The prompt piped to opencode should NOT contain raw diff content."""
    diff_text = _build_diff_hunk("src/app.py", "print('app')")
    _, prompt_text, _ = _run_reviewer(diff_text, tmp_path, reviewer_env)

    # Should NOT have inline diff content
    assert "diff --git" not in prompt_text
    assert "@@" not in prompt_text


def test_diff_file_is_unmodified(
    tmp_path: Path, reviewer_env: dict[str, str]
) -> None:
    """The diff file should be passed through unmodified (no filtering)."""
    diff_text = (
        _build_diff_hunk("src/app.py", "print('app')")
        + _build_diff_hunk("package-lock.json", '{"name":"demo"}')
    )
    _, _, diff_file = _run_reviewer(diff_text, tmp_path, reviewer_env)

    # The diff file still contains ALL content — agent decides what to skip
    content = diff_file.read_text()
    assert "diff --git a/src/app.py" in content
    assert "diff --git a/package-lock.json" in content


def test_all_agents_have_test_only_rule() -> None:
    files_and_phrases = {
        "correctness.md": "no correctness concerns",
        "architecture.md": "no architecture concerns",
        "security.md": "no security concerns",
        "performance.md": "no performance concerns",
        "maintainability.md": "no maintainability concerns",
    }

    for filename, phrase in files_and_phrases.items():
        content = (AGENTS_DIR / filename).read_text()
        assert "Test-only PRs:" in content
        assert phrase in content
