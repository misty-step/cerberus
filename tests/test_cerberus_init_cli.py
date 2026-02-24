"""Behavior tests for the cerberus init CLI."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
CLI = REPO_ROOT / "bin" / "cerberus.js"
TEMPLATE = (REPO_ROOT / "templates" / "consumer-workflow.yml").read_text()


def make_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)


def setup_fake_gh(bin_dir: Path, calls_file: Path) -> None:
    make_executable(
        bin_dir / "gh",
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "if [[ \"${1:-}\" == \"--version\" ]]; then\n"
            "  echo \"gh version test\"\n"
            "  exit 0\n"
            "fi\n"
            "if [[ \"${1:-}\" == \"secret\" && \"${2:-}\" == \"set\" && \"${3:-}\" == \"OPENROUTER_API_KEY\" ]]; then\n"
            f"  printf '%s\\n' \"$*\" >> {str(calls_file)!r}\n"
            "  exit 0\n"
            "fi\n"
            "echo \"unexpected gh args: $*\" >&2\n"
            "exit 1\n"
        ),
    )


def build_env(bin_dir: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    if extra:
        env.update(extra)
    return env


@pytest.mark.skipif(not shutil.which("node"), reason="node is required")
def test_help_output() -> None:
    result = subprocess.run(
        ["node", str(CLI)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0
    assert "Usage: cerberus init" in result.stdout


@pytest.mark.skipif(not shutil.which("node"), reason="node is required")
def test_unknown_command_fails() -> None:
    result = subprocess.run(
        ["node", str(CLI), "unknown"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode != 0
    assert "Unknown command: unknown" in result.stderr


@pytest.mark.skipif(not shutil.which("node"), reason="node is required")
def test_init_creates_workflow_when_missing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_file = tmp_path / "gh-calls.txt"
    setup_fake_gh(bin_dir, calls_file)

    result = subprocess.run(
        ["node", str(CLI), "init"],
        cwd=repo,
        env=build_env(bin_dir, {"OPENROUTER_API_KEY": "env-key"}),
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    workflow = repo / ".github" / "workflows" / "cerberus.yml"
    assert workflow.exists()
    assert workflow.read_text() == TEMPLATE
    assert "Created .github/workflows/cerberus.yml" in result.stdout
    gh_call = calls_file.read_text()
    assert "secret set OPENROUTER_API_KEY" in gh_call
    assert "--body" not in gh_call
    assert "env-key" not in gh_call


@pytest.mark.skipif(not shutil.which("node"), reason="node is required")
def test_init_preserves_custom_existing_workflow(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    custom_workflow = repo / ".github" / "workflows" / "cerberus.yml"
    custom_workflow.parent.mkdir(parents=True, exist_ok=True)
    custom_workflow.write_text("name: Custom Cerberus\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_file = tmp_path / "gh-calls.txt"
    setup_fake_gh(bin_dir, calls_file)

    result = subprocess.run(
        ["node", str(CLI), "init"],
        cwd=repo,
        env=build_env(bin_dir, {"OPENROUTER_API_KEY": "env-key"}),
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert custom_workflow.read_text() == "name: Custom Cerberus\n"
    assert "Left unchanged: .github/workflows/cerberus.yml" in result.stdout
    assert "No workflow file changes to commit." in result.stdout
    gh_call = calls_file.read_text()
    assert "secret set OPENROUTER_API_KEY" in gh_call
    assert "--body" not in gh_call
    assert "env-key" not in gh_call


@pytest.mark.skipif(not shutil.which("node"), reason="node is required")
def test_init_requires_key_when_non_interactive_and_env_missing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_file = tmp_path / "gh-calls.txt"
    setup_fake_gh(bin_dir, calls_file)

    env = build_env(bin_dir)
    env.pop("OPENROUTER_API_KEY", None)

    result = subprocess.run(
        ["node", str(CLI), "init"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode != 0
    assert "No API key in OPENROUTER_API_KEY and no interactive TTY available for gh prompt." in result.stderr
    assert not calls_file.exists()
