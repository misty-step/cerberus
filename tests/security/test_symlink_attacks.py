"""Verify staging refuses symlinks in the workspace.

If an attacker places a symlink at opencode.json or .opencode/agents/
in the target workspace, the staging logic must refuse to overwrite it
rather than following the link to an attacker-controlled location.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
RUN_REVIEWER = REPO_ROOT / "scripts" / "run-reviewer.sh"


def _write_fake_cerberus_root(root: Path, perspective: str = "security") -> None:
    (root / "defaults").mkdir(parents=True)
    (root / "templates").mkdir(parents=True)
    (root / ".opencode" / "agents").mkdir(parents=True)
    (root / "defaults" / "config.yml").write_text(
        f"- name: SENTINEL\n  perspective: {perspective}\n"
    )
    (root / "templates" / "review-prompt.md").write_text(
        "{{DIFF_FILE}}\n{{PERSPECTIVE}}\n"
    )
    (root / "opencode.json").write_text("{}\n")
    (root / ".opencode" / "agents" / f"{perspective}.md").write_text(
        "---\ndescription: test\n---\ntest\n"
    )


def _make_env(
    bin_dir: Path, diff_file: Path, cerberus_root: Path
) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["CERBERUS_ROOT"] = str(cerberus_root)
    env["GH_DIFF_FILE"] = str(diff_file)
    env["OPENROUTER_API_KEY"] = "test-key-not-real"
    env["REVIEW_TIMEOUT"] = "5"
    return env


def test_symlink_opencode_json_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    cerberus_root = tmp_path / "cerberus"
    _write_fake_cerberus_root(cerberus_root)

    # Place symlink at workspace/opencode.json
    target = tmp_path / "evil-target.json"
    target.write_text("{}")
    (workspace / "opencode.json").symlink_to(target)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "opencode").write_text("#!/usr/bin/env bash\necho fail\nexit 99\n")
    (bin_dir / "opencode").chmod(0o755)

    diff_file = tmp_path / "diff.patch"
    diff_file.write_text("diff --git a/f b/f\n+x\n")

    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=_make_env(bin_dir, diff_file, cerberus_root),
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "refusing to overwrite non-regular file" in result.stderr


def test_symlink_opencode_dir_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    cerberus_root = tmp_path / "cerberus"
    _write_fake_cerberus_root(cerberus_root)

    # Place symlink at workspace/.opencode -> attacker dir
    evil_dir = tmp_path / "evil-opencode"
    evil_dir.mkdir()
    (workspace / ".opencode").symlink_to(evil_dir)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "opencode").write_text("#!/usr/bin/env bash\necho fail\nexit 99\n")
    (bin_dir / "opencode").chmod(0o755)

    diff_file = tmp_path / "diff.patch"
    diff_file.write_text("diff --git a/f b/f\n+x\n")

    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=_make_env(bin_dir, diff_file, cerberus_root),
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "refusing to write into non-directory" in result.stderr


def test_symlink_agent_file_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".opencode" / "agents").mkdir(parents=True)

    cerberus_root = tmp_path / "cerberus"
    _write_fake_cerberus_root(cerberus_root)

    # Place symlink at workspace/.opencode/agents/security.md
    evil_target = tmp_path / "evil-agent.md"
    evil_target.write_text("evil")
    (workspace / ".opencode" / "agents" / "security.md").symlink_to(evil_target)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "opencode").write_text("#!/usr/bin/env bash\necho fail\nexit 99\n")
    (bin_dir / "opencode").chmod(0o755)

    diff_file = tmp_path / "diff.patch"
    diff_file.write_text("diff --git a/f b/f\n+x\n")

    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=_make_env(bin_dir, diff_file, cerberus_root),
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "refusing to overwrite non-regular file" in result.stderr
