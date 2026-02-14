"""Standalone tests for git hooks (no conftest dependencies)."""
import os
import subprocess
import tempfile
import shutil
from pathlib import Path

# Dummy conftest values to avoid import issues
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

def test_setup_script_exists():
    """scripts/setup-hooks.sh must exist and be executable."""
    setup_script = Path("scripts/setup-hooks.sh")
    assert setup_script.exists(), "setup-hooks.sh must exist"
    assert os.access(setup_script, os.X_OK), "setup-hooks.sh must be executable"
    print("✓ test_setup_script_exists passed")

def test_githooks_directory_exists():
    """.githooks directory must exist with hook scripts."""
    githooks = Path(".githooks")
    assert githooks.exists(), ".githooks directory must exist"
    assert githooks.is_dir(), ".githooks must be a directory"
    print("✓ test_githooks_directory_exists passed")

def test_pre_commit_hook_exists():
    """pre-commit hook must exist and be executable."""
    hook = Path(".githooks/pre-commit")
    assert hook.exists(), "pre-commit hook must exist"
    assert os.access(hook, os.X_OK), "pre-commit must be executable"
    print("✓ test_pre_commit_hook_exists passed")

def test_pre_push_hook_exists():
    """pre-push hook must exist and be executable."""
    hook = Path(".githooks/pre-push")
    assert hook.exists(), "pre-push hook must exist"
    assert os.access(hook, os.X_OK), "pre-push must be executable"
    print("✓ test_pre_push_hook_exists passed")

def test_makefile_exists():
    """Makefile must exist."""
    assert Path("Makefile").exists(), "Makefile must exist"
    print("✓ test_makefile_exists passed")

def test_pre_commits_on_valid_shell():
    """pre-commit should pass on valid shell script."""
    import tempfile
    import subprocess
    from pathlib import Path
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo = Path(tmp_dir) / "repo"
        repo.mkdir()
        
        # Init git repo
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        
        # Copy hooks
        githooks = Path(".githooks")
        hooks_dest = repo / ".git" / "hooks"
        if hooks_dest.exists():
            shutil.rmtree(hooks_dest)
        shutil.copytree(githooks, hooks_dest)
        
        # Create valid shell script (SC-compliant)
        script = repo / "scripts" / "test.sh"
        script.parent.mkdir()
        script.write_text("#!/bin/bash\n# Test script\necho 'hello world'")
        
        # Stage and test pre-commit
        subprocess.run(["git", "add", "scripts/test.sh"], cwd=repo, check=True)
        result = subprocess.run(
            [repo / ".git" / "hooks" / "pre-commit"],
            cwd=repo,
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, f"pre-commit failed: {result.stderr}"
        print("✓ test_pre_commits_on_valid_shell passed")

def test_pre_commits_fails_on_bad_shell():
    """pre-commit should fail on bad shell script."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo = Path(tmp_dir) / "repo"
        repo.mkdir()
        
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        
        githooks = Path(".githooks")
        hooks_dest = repo / ".git" / "hooks"
        if hooks_dest.exists():
            shutil.rmtree(hooks_dest)
        shutil.copytree(githooks, hooks_dest)
        
        # Create bad shell script (undefined variable)
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
        # Shellcheck should flag unquoted variable as error
        assert result.returncode != 0, "pre-commit should fail on bad shell script"
        print("✓ test_pre_commits_fails_on_bad_shell passed")

def test_pre_commits_fails_on_bad_python():
    """pre-commit should fail on Python with syntax errors."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo = Path(tmp_dir) / "repo"
        repo.mkdir()
        
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        
        githooks = Path(".githooks")
        hooks_dest = repo / ".git" / "hooks"
        if hooks_dest.exists():
            shutil.rmtree(hooks_dest)
        shutil.copytree(githooks, hooks_dest)
        
        # Create Python with syntax error
        script = repo / "scripts" / "bad.py"
        script.parent.mkdir()
        script.write_text("print('hello'")  # Missing closing paren
        
        subprocess.run(["git", "add", "scripts/bad.py"], cwd=repo, check=True)
        
        result = subprocess.run(
            [repo / ".git" / "hooks" / "pre-commit"],
            cwd=repo,
            capture_output=True,
            text=True
        )
        assert result.returncode != 0, "pre-commit should fail on bad Python syntax"
        print("✓ test_pre_commits_fails_on_bad_python passed")

def test_contributing_mentions_hooks():
    """CONTRIBUTING.md must mention git hooks."""
    contributing = Path("CONTRIBUTING.md").read_text()
    assert "hook" in contributing.lower(), "CONTRIBUTING.md must mention hooks"
    assert "make setup" in contributing, "CONTRIBUTING.md must document make setup"
    print("✓ test_contributing_mentions_hooks passed")

if __name__ == "__main__":
    os.chdir(Path(__file__).parent.parent)

    tests = [
        test_setup_script_exists,
        test_githooks_directory_exists,
        test_pre_commit_hook_exists,
        test_pre_push_hook_exists,
        test_makefile_exists,
        test_pre_commits_on_valid_shell,
        test_pre_commits_fails_on_bad_shell,
        test_pre_commits_fails_on_bad_python,
        test_contributing_mentions_hooks,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__} failed: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__} errored: {e}")
            failed += 1

    print(f"\n{passed}/{len(tests)} tests passed")
    if failed > 0:
        exit(1)
