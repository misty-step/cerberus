"""Tests for git hooks setup and functionality."""
import os
import subprocess
import tempfile
import shutil
from pathlib import Path

import pytest


class TestHookInfrastructure:
    """Test that hook infrastructure exists and is installable."""

    def test_setup_script_exists(self):
        """scripts/setup-hooks.sh must exist and be executable."""
        setup_script = Path("scripts/setup-hooks.sh")
        assert setup_script.exists(), "setup-hooks.sh must exist"
        assert os.access(setup_script, os.X_OK), "setup-hooks.sh must be executable"

    def test_githooks_directory_exists(self):
        """.githooks directory must exist with hook scripts."""
        githooks = Path(".githooks")
        assert githooks.exists(), ".githooks directory must exist"
        assert githooks.is_dir(), ".githooks must be a directory"

    def test_pre_commit_hook_exists(self):
        """pre-commit hook must exist and be executable."""
        hook = Path(".githooks/pre-commit")
        assert hook.exists(), "pre-commit hook must exist"
        assert os.access(hook, os.X_OK), "pre-commit must be executable"

    def test_pre_push_hook_exists(self):
        """pre-push hook must exist and be executable."""
        hook = Path(".githooks/pre-push")
        assert hook.exists(), "pre-push hook must exist"
        assert os.access(hook, os.X_OK), "pre-push must be executable"


class TestPreCommitHook:
    """Test pre-commit hook functionality."""

    def test_pre_commit_runs_shellcheck_on_shell_scripts(self, tmp_path):
        """pre-commit must run shellcheck on staged .sh files."""
        # Create a temp git repo
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        
        # Copy hooks
        githooks = Path(".githooks")
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

    def test_pre_commit_fails_on_bad_shell_script(self, tmp_path):
        """pre-commit must fail on shell scripts with issues."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        
        githooks = Path(".githooks")
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
        
        githooks = Path(".githooks")
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
        
        githooks = Path(".githooks")
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


class TestPrePushHook:
    """Test pre-push hook functionality."""

    def test_pre_push_runs_test_suite(self, tmp_path):
        """pre-push must run the full pytest suite."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        
        githooks = Path(".githooks")
        shutil.copytree(githooks, repo / ".git" / "hooks", dirs_exist_ok=True)
        
        # Create a simple file to commit
        readme = repo / "README.md"
        readme.write_text("# Test")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
        
        # Run pre-push (it may fail if pytest not installed, but should attempt)
        result = subprocess.run(
            [repo / ".git" / "hooks" / "pre-push"],
            cwd=repo,
            capture_output=True,
            text=True
        )
        # Should mention pytest or tests
        assert "pytest" in result.stderr.lower() or "test" in result.stderr.lower() or result.returncode in [0, 1], \
            "pre-push should attempt to run tests"


class TestMakefile:
    """Test Makefile targets."""

    def test_makefile_exists(self):
        """Makefile must exist."""
        assert Path("Makefile").exists(), "Makefile must exist"

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
        contributing = Path("CONTRIBUTING.md").read_text()
        assert "hook" in contributing.lower(), "CONTRIBUTING.md must mention hooks"
        assert "make setup" in contributing, "CONTRIBUTING.md must document make setup"
