"""Verify workspace symlinks are inert for the Pi runtime.

The runtime now executes in an isolated HOME and does not stage config/agent
files into the current working directory. Symlinks in the workspace should not
be touched or followed.
"""

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
RUN_REVIEWER = REPO_ROOT / "scripts" / "run-reviewer.sh"


def _make_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _make_stub_pi(path: Path) -> None:
    _make_executable(
        path,
        (
            "#!/usr/bin/env bash\n"
            "cat <<'REVIEW'\n"
            "```json\n"
            '{"reviewer":"STUB","perspective":"security","verdict":"PASS",'
            '"confidence":0.95,"summary":"Stub",'
            '"findings":[],"stats":{"files_reviewed":1,"files_with_issues":0,'
            '"critical":0,"major":0,"minor":0,"info":0}}\n'
            "```\n"
            "REVIEW\n"
        ),
    )


def _base_env(bin_dir: Path, diff_file: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["CERBERUS_ROOT"] = str(REPO_ROOT)
    env["GH_DIFF_FILE"] = str(diff_file)
    env["OPENROUTER_API_KEY"] = "test-key-not-real"
    env["REVIEW_TIMEOUT"] = "5"
    env["OPENCODE_MAX_STEPS"] = "5"
    env["CERBERUS_TEST_NO_SLEEP"] = "1"
    return env


def test_workspace_opencode_json_symlink_is_untouched(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    target = tmp_path / "target.json"
    target.write_text("safe\n")
    link = workspace / "opencode.json"
    link.symlink_to(target)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_stub_pi(bin_dir / "pi")

    diff_file = tmp_path / "diff.patch"
    diff_file.write_text("diff --git a/f.py b/f.py\n+pass\n")

    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=_base_env(bin_dir, diff_file),
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert link.is_symlink()
    assert target.read_text() == "safe\n"


def test_workspace_agent_symlink_is_untouched(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".opencode" / "agents").mkdir(parents=True)

    target = tmp_path / "evil-agent.md"
    target.write_text("evil\n")
    link = workspace / ".opencode" / "agents" / "security.md"
    link.symlink_to(target)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_stub_pi(bin_dir / "pi")

    diff_file = tmp_path / "diff.patch"
    diff_file.write_text("diff --git a/f.py b/f.py\n+pass\n")

    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=_base_env(bin_dir, diff_file),
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert link.is_symlink()
    assert target.read_text() == "evil\n"
