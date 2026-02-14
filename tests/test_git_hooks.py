"""Tests for git hooks setup and functionality."""
import os
import subprocess
import tempfile
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SHELLCHECK_AVAILABLE = shutil.which("shellcheck") is not None


class TestHookInfrastructure:
    """Test that hook infrastructure exists and is installable."""

    def test_setup_script_exists(self):
        """scripts/setup-hooks.sh must exist and be executable."""
        setup_script = REPO_ROOT / "scripts/setup-hooks.sh"
        assert setup_script.exists(), "setup-hooks.sh must exist"
        assert os.access(setup_script, os.X_OK), "setup-hooks.sh must be executable"

    def test_githooks_directory_exists(self):
        """.githooks directory must exist with hook scripts."""
        githooks = REPO_ROOT / ".githooks"
        assert githooks.exists(), ".githooks directory must exist"
        assert githooks.is_dir(), ".githooks must be a directory"

    def test_pre_commit_hook_exists(self):
        """pre-commit hook must exist and be executable."""
        hook = REPO_ROOT / ".githooks/pre-commit"
        assert hook.exists(), "pre-commit hook must exist"
        assert os.access(hook, os.X_OK), "pre-commit must be executable"

    def test_pre_push_hook_exists(self):
        """pre-push hook must exist and be executable."""
        hook = REPO_ROOT / ".githooks/pre-push"
        assert hook.exists(), "pre-push hook must exist"
        assert os.access(hook, os.X_OK), "pre-push must be executable"


class TestPreCommitHook:
    """Test pre-commit hook functionality."""

    @pytest.mark.skipif(not SHELLCHECK_AVAILABLE, reason="shellcheck not installed")
    def test_pre_commit_runs_shellcheck_on_shell_scripts(self, tmp_path):
        """pre-commit must run shellcheck on staged .sh files."""
        # Create a temp git repo
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        
        # Copy hooks
        githooks = REPO_ROOT / ".githooks"
        shutil.copytree(githooks, repo / ".git" / "hooks", dirs_exist_ok=True)
        
        # Create a shell script with error
        script = repo / "scripts" / "test.sh"
        script.parent.mkdir()
        script.write_text("#!/bin/bash\n[[ $1 == \"test\" ]]")  # Modern bash, should pass
        
        # Stage it
        subprocess.run(["git", "add", "scripts/test.sh"], cwd=repo, check=True)
        
        # Run pre-commit
        result = subprocess.run(
            [repo / ".git" / "hooks" / "pre-commit"],
            cwd=repo,
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, f"pre-commit failed: {result.stderr}"

    @pytest.mark.skipif(not SHELLCHECK_AVAILABLE, reason="shellcheck not installed")
    def test_pre_commit_fails_on_bad_shell_script(self, tmp_path):
        """pre-commit must fail on shell scripts with issues."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        
        githooks = REPO_ROOT / ".githooks"
        shutil.copytree(githooks, repo / ".git" / "hooks", dirs_exist_ok=True)
        
        # Create a shell script with clear error (undefined variable without check)
        script = repo / "scripts" / "bad.sh"
        script.parent.mkdir()
        script.write_text("#!/bin/sh\necho $UNDEFINED_VAR")
        
        subprocess.run(["git", "add", "scripts/bad.sh"], cwd=repo, check=True)
        
        result = subprocess.run(
            [repo / ".git" / "hooks" / "pre-commit"],
            cwd=repo,
            capture_output=True,
            text=True
        )
        assert result.returncode != 0, "pre-commit should fail on bad shell script"

    def test_pre_commit_runs_py_compile_on_python_scripts(self, tmp_path):
        """pre-commit must run py_compile on staged .py files in scripts/."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        
        githooks = REPO_ROOT / ".githooks"
        shutil.copytree(githooks, repo / ".git" / "hooks", dirs_exist_ok=True)
        
        # Create a valid Python file
        script = repo / "scripts" / "test.py"
        script.parent.mkdir()
        script.write_text("print('hello')")
        
        subprocess.run(["git", "add", "scripts/test.py"], cwd=repo, check=True)
        
        result = subprocess.run(
            [repo / ".git" / "hooks" / "pre-commit"],
            cwd=repo,
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, f"pre-commit failed: {result.stderr}"

    def test_pre_commit_fails_on_bad_python_syntax(self, tmp_path):
        """pre-commit must fail on Python files with syntax errors."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        
        githooks = REPO_ROOT / ".githooks"
        shutil.copytree(githooks, repo / ".git" / "hooks", dirs_exist_ok=True)
        
        # Create Python file with syntax error
        script = repo / "scripts" / "bad.py"
        script.parent.mkdir()
        script.write_text("print('hello'\n")  # Missing closing paren
        
        subprocess.run(["git", "add", "scripts/bad.py"], cwd=repo, check=True)
        
        result = subprocess.run(
            [repo / ".git" / "hooks" / "pre-commit"],
            cwd=repo,
            capture_output=True,
            text=True
        )
        assert result.returncode != 0, "pre-commit should fail on bad Python syntax"

    def test_pre_commit_passes_valid_yaml(self, tmp_path):
        """pre-commit must pass on valid YAML files."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

        githooks = REPO_ROOT / ".githooks"
        shutil.copytree(githooks, repo / ".git" / "hooks", dirs_exist_ok=True)

        yml = repo / "config.yml"
        yml.write_text("key: value\nlist:\n  - item1\n  - item2\n")

        subprocess.run(["git", "add", "config.yml"], cwd=repo, check=True)

        result = subprocess.run(
            [repo / ".git" / "hooks" / "pre-commit"],
            cwd=repo,
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, f"pre-commit failed on valid YAML: {result.stderr}"

    def test_pre_commit_fails_invalid_yaml(self, tmp_path):
        """pre-commit must fail on invalid YAML files."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

        githooks = REPO_ROOT / ".githooks"
        shutil.copytree(githooks, repo / ".git" / "hooks", dirs_exist_ok=True)

        yml = repo / "bad.yml"
        yml.write_text("key: value\n  bad indent: broken\n    - not valid\n")

        subprocess.run(["git", "add", "bad.yml"], cwd=repo, check=True)

        result = subprocess.run(
            [repo / ".git" / "hooks" / "pre-commit"],
            cwd=repo,
            capture_output=True,
            text=True
        )
        assert result.returncode != 0, "pre-commit should fail on invalid YAML"

    def test_pre_commit_passes_valid_json(self, tmp_path):
        """pre-commit must pass on valid JSON files."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

        githooks = REPO_ROOT / ".githooks"
        shutil.copytree(githooks, repo / ".git" / "hooks", dirs_exist_ok=True)

        jsonf = repo / "config.json"
        jsonf.write_text('{"key": "value", "list": [1, 2, 3]}')

        subprocess.run(["git", "add", "config.json"], cwd=repo, check=True)

        result = subprocess.run(
            [repo / ".git" / "hooks" / "pre-commit"],
            cwd=repo,
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, f"pre-commit failed on valid JSON: {result.stderr}"

    def test_pre_commit_fails_invalid_json(self, tmp_path):
        """pre-commit must fail on invalid JSON files."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)

        githooks = REPO_ROOT / ".githooks"
        shutil.copytree(githooks, repo / ".git" / "hooks", dirs_exist_ok=True)

        jsonf = repo / "bad.json"
        jsonf.write_text('{"key": "value", missing_quotes: true}')

        subprocess.run(["git", "add", "bad.json"], cwd=repo, check=True)

        result = subprocess.run(
            [repo / ".git" / "hooks" / "pre-commit"],
            cwd=repo,
            capture_output=True,
            text=True
        )
        assert result.returncode != 0, "pre-commit should fail on invalid JSON"


class TestSetupScript:
    """Test setup-hooks.sh installs hooks correctly."""

    def test_setup_hooks_installs_hooks(self, tmp_path):
        """setup-hooks.sh must install hook files into .git/hooks/."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

        shutil.copytree(REPO_ROOT / ".githooks", repo / ".githooks")
        (repo / "scripts").mkdir()
        shutil.copy2(REPO_ROOT / "scripts/setup-hooks.sh", repo / "scripts" / "setup-hooks.sh")

        result = subprocess.run(
            ["bash", repo / "scripts" / "setup-hooks.sh"],
            cwd=repo,
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, f"setup-hooks.sh failed: {result.stderr}"
        assert (repo / ".git" / "hooks" / "pre-commit").exists(), "pre-commit hook must be installed"
        assert (repo / ".git" / "hooks" / "pre-push").exists(), "pre-push hook must be installed"
        assert os.access(repo / ".git" / "hooks" / "pre-commit", os.X_OK), "pre-commit must be executable"
        assert os.access(repo / ".git" / "hooks" / "pre-push", os.X_OK), "pre-push must be executable"

    def test_setup_hooks_sets_config(self, tmp_path):
        """setup-hooks.sh must set git config core.hooksPath."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)

        shutil.copytree(REPO_ROOT / ".githooks", repo / ".githooks")
        (repo / "scripts").mkdir()
        shutil.copy2(REPO_ROOT / "scripts/setup-hooks.sh", repo / "scripts" / "setup-hooks.sh")

        subprocess.run(
            ["bash", repo / "scripts" / "setup-hooks.sh"],
            cwd=repo,
            check=True,
            capture_output=True
        )

        result = subprocess.run(
            ["git", "config", "--local", "core.hooksPath"],
            cwd=repo,
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, "core.hooksPath must be set"
        assert "hooks" in result.stdout, f"core.hooksPath should point to hooks dir, got: {result.stdout.strip()}"


class TestPrePushHook:
    """Test pre-push hook functionality."""

    def test_pre_push_runs_test_suite(self, tmp_path):
        """pre-push must run the full pytest suite."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        
        githooks = REPO_ROOT / ".githooks"
        shutil.copytree(githooks, repo / ".git" / "hooks", dirs_exist_ok=True)
        
        # Create a simple file to commit
        readme = repo / "README.md"
        readme.write_text("# Test")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
        
        # Run pre-push
        result = subprocess.run(
            [repo / ".git" / "hooks" / "pre-push"],
            cwd=repo,
            capture_output=True,
            text=True
        )
        combined = (result.stdout + result.stderr).lower()
        # Hook must identify itself and mention running checks
        assert "pre-push" in combined, "pre-push should identify itself"
        assert "test" in combined or "pytest" in combined, \
            "pre-push should mention running tests"
        assert result.returncode in [0, 1], \
            f"pre-push should exit 0 (pass) or 1 (fail), got {result.returncode}"


class TestMakefile:
    """Test Makefile targets."""

    def test_makefile_exists(self):
        """Makefile must exist."""
        assert (REPO_ROOT / "Makefile").exists(), "Makefile must exist"

    def test_make_setup_exists(self):
        """make setup target must exist."""
        result = subprocess.run(
            ["make", "-n", "setup"],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, "make setup target must exist"


class TestHookDocumentation:
    """Test that hooks are documented."""

    def test_contributing_mentions_hooks(self):
        """CONTRIBUTING.md must mention git hooks."""
        contributing = (REPO_ROOT / "CONTRIBUTING.md").read_text()
        assert "hook" in contributing.lower(), "CONTRIBUTING.md must mention hooks"
        assert "make setup" in contributing, "CONTRIBUTING.md must document make setup"
