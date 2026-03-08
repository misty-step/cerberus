"""Behavior tests for the cerberus init CLI."""

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
CLI = REPO_ROOT / "bin" / "cerberus.js"
TEMPLATE = (REPO_ROOT / "templates" / "consumer-workflow-reusable.yml").read_text()
README = (REPO_ROOT / "README.md").read_text()
PACKAGE = json.loads((REPO_ROOT / "package.json").read_text())


def make_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)


def setup_gh(
    bin_dir: Path,
    *,
    calls_file: Path | None = None,
    stderr_message: str | None = None,
) -> None:
    secret_handler = "echo \"unexpected gh args: $*\" >&2\nexit 1\n"
    if calls_file is not None:
        secret_handler = (
            "if [[ \"${3:-}\" == \"CERBERUS_OPENROUTER_API_KEY\" || \"${3:-}\" == \"OPENROUTER_API_KEY\" ]]; then\n"
            f"  printf '%s\\n' \"$*\" >> {str(calls_file)!r}\n"
            "  exit 0\n"
            "fi\n"
            "echo \"unexpected gh args: $*\" >&2\n"
            "exit 1\n"
        )
    if stderr_message is not None:
        secret_handler = f"echo {stderr_message!r} >&2\nexit 1\n"

    make_executable(
        bin_dir / "gh",
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "if [[ \"${1:-}\" == \"--version\" ]]; then\n"
            "  echo \"gh version test\"\n"
            "  exit 0\n"
            "fi\n"
            "if [[ \"${1:-}\" == \"secret\" && \"${2:-}\" == \"set\" ]]; then\n"
            f"{secret_handler}"
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
    setup_gh(bin_dir, calls_file=calls_file)

    result = subprocess.run(
        ["node", str(CLI), "init"],
        cwd=repo,
        env=build_env(bin_dir, {"CERBERUS_OPENROUTER_API_KEY": "env-key"}),
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
    assert "secret set CERBERUS_OPENROUTER_API_KEY" in gh_call
    assert "--body" not in gh_call
    assert "env-key" not in gh_call


@pytest.mark.skipif(not shutil.which("node"), reason="node is required")
def test_init_accepts_legacy_openrouter_env_key(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_file = tmp_path / "gh-calls.txt"
    setup_gh(bin_dir, calls_file=calls_file)

    env = build_env(bin_dir, {"OPENROUTER_API_KEY": "legacy-env-key"})
    env.pop("CERBERUS_OPENROUTER_API_KEY", None)

    result = subprocess.run(
        ["node", str(CLI), "init"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    gh_call = calls_file.read_text()
    assert "secret set CERBERUS_OPENROUTER_API_KEY" in gh_call
    assert "secret set OPENROUTER_API_KEY" not in gh_call
    assert "legacy-env-key" not in gh_call


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
    setup_gh(bin_dir, calls_file=calls_file)

    result = subprocess.run(
        ["node", str(CLI), "init"],
        cwd=repo,
        env=build_env(bin_dir, {"CERBERUS_OPENROUTER_API_KEY": "env-key"}),
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert custom_workflow.read_text() == "name: Custom Cerberus\n"
    assert "Left unchanged: .github/workflows/cerberus.yml" in result.stdout
    assert "No workflow file changes to commit." in result.stdout
    gh_call = calls_file.read_text()
    assert "secret set CERBERUS_OPENROUTER_API_KEY" in gh_call
    assert "--body" not in gh_call
    assert "env-key" not in gh_call


@pytest.mark.skipif(not shutil.which("node"), reason="node is required")
def test_init_mirrors_legacy_secret_for_custom_legacy_workflow(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    custom_workflow = repo / ".github" / "workflows" / "cerberus.yml"
    custom_workflow.parent.mkdir(parents=True, exist_ok=True)
    custom_workflow.write_text(
        "name: Cerberus\n"
        "jobs:\n"
        "  review:\n"
        "    uses: misty-step/cerberus/.github/workflows/cerberus.yml@master\n"
        "    secrets:\n"
        "      api-key: ${{ secrets.OPENROUTER_API_KEY }}\n"
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_file = tmp_path / "gh-calls.txt"
    setup_gh(bin_dir, calls_file=calls_file)

    result = subprocess.run(
        ["node", str(CLI), "init"],
        cwd=repo,
        env=build_env(bin_dir, {"CERBERUS_OPENROUTER_API_KEY": "env-key"}),
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    gh_call = calls_file.read_text()
    assert "secret set CERBERUS_OPENROUTER_API_KEY" in gh_call
    assert "secret set OPENROUTER_API_KEY" in gh_call
    assert "env-key" not in gh_call
    assert "mirrored that legacy secret" in result.stdout


@pytest.mark.skipif(not shutil.which("node"), reason="node is required")
def test_init_requires_key_when_non_interactive_and_env_missing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_file = tmp_path / "gh-calls.txt"
    setup_gh(bin_dir, calls_file=calls_file)

    env = build_env(bin_dir)
    env.pop("CERBERUS_OPENROUTER_API_KEY", None)
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
    assert "No API key in CERBERUS_OPENROUTER_API_KEY (or OPENROUTER_API_KEY) and no interactive TTY available for gh prompt." in result.stderr
    assert not calls_file.exists()


@pytest.mark.skipif(not shutil.which("node"), reason="node is required")
def test_init_trims_whitespace_keys(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_file = tmp_path / "gh-calls.txt"
    setup_gh(bin_dir, calls_file=calls_file)

    result = subprocess.run(
        ["node", str(CLI), "init"],
        cwd=repo,
        env=build_env(
            bin_dir,
            {"CERBERUS_OPENROUTER_API_KEY": "  ", "OPENROUTER_API_KEY": "real-key"},
        ),
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0
    gh_call = calls_file.read_text()
    assert "secret set CERBERUS_OPENROUTER_API_KEY" in gh_call
    assert "real-key" not in gh_call


@pytest.mark.skipif(not shutil.which("node"), reason="node is required")
def test_init_fails_outside_git_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_file = tmp_path / "gh-calls.txt"
    setup_gh(bin_dir, calls_file=calls_file)

    result = subprocess.run(
        ["node", str(CLI), "init"],
        cwd=repo,
        env=build_env(bin_dir, {"CERBERUS_OPENROUTER_API_KEY": "env-key"}),
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode != 0
    assert "must run inside a git repository" in result.stderr
    assert not calls_file.exists()


@pytest.mark.skipif(not shutil.which("node"), reason="node is required")
def test_init_surfaces_gh_secret_set_failure(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    setup_gh(bin_dir, stderr_message="gh secret set boom")

    result = subprocess.run(
        ["node", str(CLI), "init"],
        cwd=repo,
        env=build_env(bin_dir, {"CERBERUS_OPENROUTER_API_KEY": "env-key"}),
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode != 0
    assert "Failed to set CERBERUS_OPENROUTER_API_KEY in repository secrets" in result.stderr
    assert "gh secret set boom" in result.stderr


@pytest.mark.skipif(not shutil.which("node"), reason="node is required")
def test_init_fails_when_workflow_directory_is_not_writable(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)

    workflows_dir = repo / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    workflows_dir.chmod(0)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_file = tmp_path / "gh-calls.txt"
    setup_gh(bin_dir, calls_file=calls_file)

    try:
        result = subprocess.run(
            ["node", str(CLI), "init"],
            cwd=repo,
            env=build_env(bin_dir, {"CERBERUS_OPENROUTER_API_KEY": "env-key"}),
            capture_output=True,
            text=True,
            timeout=20,
        )
    finally:
        workflows_dir.chmod(0o755)

    assert result.returncode != 0
    assert "EACCES" in result.stderr or "permission denied" in result.stderr.lower()
    assert not calls_file.exists()


def test_readme_npx_command_matches_package_name() -> None:
    match = re.search(r"`npx\s+([^`\s]+)\s+init`", README)
    assert match, "README must document the cerberus init npx command"
    assert match.group(1) == PACKAGE["name"]


def test_package_metadata_is_publish_ready() -> None:
    assert PACKAGE["name"] == "@misty-step/cerberus"
    assert PACKAGE["publishConfig"] == {"access": "public"}
    assert PACKAGE["repository"] == {
        "type": "git",
        "url": "git+https://github.com/misty-step/cerberus.git",
    }


@pytest.mark.skipif(not shutil.which("npm"), reason="npm is required")
def test_package_can_be_packed_for_publish() -> None:
    result = subprocess.run(
        ["npm", "pack", "--dry-run", "--json"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )

    package = json.loads(result.stdout)[0]
    packed_files = {entry["path"] for entry in package["files"]}

    assert package["name"] == PACKAGE["name"]
    assert "bin/cerberus.js" in packed_files
    assert "templates/consumer-workflow-reusable.yml" in packed_files
    assert "templates/consumer-workflow-minimal.yml" in packed_files
    assert "templates/workflow-lint.yml" in packed_files
