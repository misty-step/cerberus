"""Tests for global model override warning (issue #155)."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
RUN_REVIEWER = REPO_ROOT / "scripts" / "run-reviewer.sh"


def make_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def make_env(bin_dir: Path, diff_file: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["CERBERUS_ROOT"] = str(REPO_ROOT)
    env["GH_DIFF_FILE"] = str(diff_file)
    env["OPENROUTER_API_KEY"] = "test-key-not-real"
    env["OPENCODE_MAX_STEPS"] = "5"
    env["REVIEW_TIMEOUT"] = "5"
    return env


def write_stub_opencode(path: Path) -> None:
    make_executable(
        path,
        (
            "#!/usr/bin/env bash\n"
            "cat <<'REVIEW'\n"
            "```json\n"
            '{"reviewer":"STUB","perspective":"security","verdict":"PASS",'
            '"confidence":0.95,"summary":"Stub output",'
            '"findings":[],"stats":{"files_reviewed":1,"files_with_issues":0,'
            '"critical":0,"major":0,"minor":0,"info":0}}\n'
            "```\n"
            "REVIEW\n"
        ),
    )


@pytest.fixture(autouse=True)
def cleanup_tmp_outputs() -> None:
    """Clean up temp files before and after each test."""
    files = [
        "/tmp/security-reviewer-name",
        "/tmp/security-primary-model",
        "/tmp/security-reviewer-default-model",
        "/tmp/security-model-used",
        "/tmp/security-parse-input",
        "/tmp/security-output.txt",
        "/tmp/security-exitcode",
    ]
    for f in files:
        Path(f).unlink(missing_ok=True)
    yield
    for f in files:
        Path(f).unlink(missing_ok=True)


def test_reviewer_default_model_file_created(tmp_path: Path) -> None:
    """When a reviewer runs, its default model (from config) should be persisted."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_stub_opencode(bin_dir / "opencode")

    diff_file = tmp_path / "test.diff"
    diff_file.write_text("diff --git a/app.py b/app.py\n+print('hello')\n")

    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=make_env(bin_dir, diff_file),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0

    # The reviewer-default-model file should exist and contain the model from config
    default_model_file = Path("/tmp/security-reviewer-default-model")
    assert default_model_file.exists(), "reviewer-default-model file should be created"
    
    # SENTINEL (security reviewer) uses minimax-m2.5 per defaults/config.yml
    default_model = default_model_file.read_text().strip()
    assert default_model == "openrouter/minimax/minimax-m2.5", (
        f"Expected SENTINEL's default model, got: {default_model}"
    )


def test_reviewer_default_model_with_override(tmp_path: Path) -> None:
    """When global model input is provided, reviewer default should still be recorded."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_stub_opencode(bin_dir / "opencode")

    diff_file = tmp_path / "test.diff"
    diff_file.write_text("diff --git a/app.py b/app.py\n+print('hello')\n")

    env = make_env(bin_dir, diff_file)
    env["OPENCODE_MODEL"] = "openrouter/google/gemini-2.5-flash"  # Global override

    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0

    # Both files should exist for comparison
    default_model_file = Path("/tmp/security-reviewer-default-model")
    primary_model_file = Path("/tmp/security-primary-model")
    
    assert default_model_file.exists(), "reviewer-default-model file should be created"
    assert primary_model_file.exists(), "primary-model file should be created"
    
    default_model = default_model_file.read_text().strip()
    primary_model = primary_model_file.read_text().strip()
    
    # The default should be SENTINEL's config model
    assert default_model == "openrouter/minimax/minimax-m2.5"
    # The primary (used) should be the override
    assert primary_model == "openrouter/google/gemini-2.5-flash"


def test_different_reviewers_have_different_defaults(tmp_path: Path) -> None:
    """Each reviewer should have its own default model from config."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_stub_opencode(bin_dir / "opencode")

    diff_file = tmp_path / "test.diff"
    diff_file.write_text("diff --git a/app.py b/app.py\n+print('hello')\n")

    reviewers = [
        ("correctness", "openrouter/moonshotai/kimi-k2.5"),   # APOLLO
        ("architecture", "openrouter/z-ai/glm-5"),            # ATHENA
        ("security", "openrouter/minimax/minimax-m2.5"),      # SENTINEL
        ("performance", "openrouter/google/gemini-3-flash-preview"),  # VULCAN
        ("maintainability", "openrouter/qwen/qwen3-max-thinking"),    # ARTEMIS
        ("testing", "openrouter/qwen/qwen3-max-thinking"),            # CASSANDRA
    ]

    for perspective, expected_model in reviewers:
        # Clean up from previous iteration
        for f in ["/tmp/" + perspective + "-" + suffix for suffix in 
                  ["reviewer-name", "primary-model", "reviewer-default-model", 
                   "model-used", "parse-input", "output.txt", "exitcode"]]:
            Path(f).unlink(missing_ok=True)

        result = subprocess.run(
            [str(RUN_REVIEWER), perspective],
            env=make_env(bin_dir, diff_file),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Failed for {perspective}: {result.stderr}"

        default_model_file = Path(f"/tmp/{perspective}-reviewer-default-model")
        assert default_model_file.exists(), f"reviewer-default-model missing for {perspective}"
        
        default_model = default_model_file.read_text().strip()
        assert default_model == expected_model, (
            f"{perspective}: expected {expected_model}, got {default_model}"
        )
