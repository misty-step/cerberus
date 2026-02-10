"""Diff filtering tests for lockfiles, generated files, and minified assets.

With context bundles, diffs are split into per-file files on disk rather than
injected inline into the prompt. These tests verify:
- Omitted files (lockfiles, generated, minified) don't get diff files written
- Included files DO get diff files written
- The prompt references the context bundle directory
- Agent configs all have the test-only rule
"""

import json
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


def _get_context_bundle(perspective: str = "correctness") -> Path:
    return Path(f"/tmp/cerberus-context-{perspective}")


def test_prompt_does_not_contain_inline_diff(
    tmp_path: Path, reviewer_env: dict[str, str]
) -> None:
    """The prompt piped to opencode should NOT contain raw diff content."""
    diff_text = _build_diff_hunk("src/app.py", "print('app')")
    _, prompt_text, _ = _run_reviewer(diff_text, tmp_path, reviewer_env)

    # Prompt should reference context bundle, not contain inline diff
    assert "Context Bundle" in prompt_text
    assert "cerberus-context-" in prompt_text
    # Should NOT have the old-style <diff> section
    assert '<diff trust="UNTRUSTED">' not in prompt_text
    assert "{{DIFF}}" not in prompt_text


def test_context_bundle_created(
    tmp_path: Path, reviewer_env: dict[str, str]
) -> None:
    """run-reviewer.sh should create a context bundle directory."""
    diff_text = _build_diff_hunk("src/app.py", "print('app')")
    _run_reviewer(diff_text, tmp_path, reviewer_env)

    bundle_dir = _get_context_bundle()
    assert bundle_dir.exists()
    assert (bundle_dir / "manifest.json").exists()
    assert (bundle_dir / "summary.md").exists()
    assert (bundle_dir / "diffs").is_dir()


def test_per_file_diff_written(
    tmp_path: Path, reviewer_env: dict[str, str]
) -> None:
    """Included files should have per-file diffs in the bundle."""
    diff_text = _build_diff_hunk("src/app.py", "print('app')")
    _run_reviewer(diff_text, tmp_path, reviewer_env)

    bundle_dir = _get_context_bundle()
    diff_file = bundle_dir / "diffs" / "src__app.py.diff"
    assert diff_file.exists()
    assert "print('app')" in diff_file.read_text()


def test_lockfile_not_in_bundle(
    tmp_path: Path, reviewer_env: dict[str, str]
) -> None:
    """Lockfiles should be omitted from the bundle diffs."""
    diff_text = (
        _build_diff_hunk("src/app.py", "print('app')")
        + _build_diff_hunk("package-lock.json", '{"name":"demo"}')
    )
    _run_reviewer(diff_text, tmp_path, reviewer_env)

    bundle_dir = _get_context_bundle()

    # App diff exists
    assert (bundle_dir / "diffs" / "src__app.py.diff").exists()

    # Lockfile diff does NOT exist
    assert not (bundle_dir / "diffs" / "package-lock.json.diff").exists()

    # Manifest shows lockfile as omitted
    manifest = json.loads((bundle_dir / "manifest.json").read_text())
    lock_entry = [f for f in manifest["files"] if f["path"] == "package-lock.json"]
    assert len(lock_entry) == 1
    assert lock_entry[0]["omitted"] is True


def test_generated_files_not_in_bundle(
    tmp_path: Path, reviewer_env: dict[str, str]
) -> None:
    diff_text = (
        _build_diff_hunk("src/app.py", "print('app')")
        + _build_diff_hunk("types.generated.ts", "export type X = string;")
    )
    _run_reviewer(diff_text, tmp_path, reviewer_env)

    bundle_dir = _get_context_bundle()
    assert not (bundle_dir / "diffs" / "types.generated.ts.diff").exists()


def test_minified_files_not_in_bundle(
    tmp_path: Path, reviewer_env: dict[str, str]
) -> None:
    diff_text = (
        _build_diff_hunk("src/app.py", "print('app')")
        + _build_diff_hunk("bundle.min.js", "var x=1;")
    )
    _run_reviewer(diff_text, tmp_path, reviewer_env)

    bundle_dir = _get_context_bundle()
    assert not (bundle_dir / "diffs" / "bundle.min.js.diff").exists()


def test_all_files_filtered_still_produces_bundle(
    tmp_path: Path, reviewer_env: dict[str, str]
) -> None:
    """Even when all files are omitted, bundle is still valid."""
    diff_text = _build_diff_hunk("package-lock.json", '{"name":"demo"}')
    _run_reviewer(diff_text, tmp_path, reviewer_env)

    bundle_dir = _get_context_bundle()
    manifest = json.loads((bundle_dir / "manifest.json").read_text())
    assert manifest["total_files"] == 1
    assert manifest["included_files"] == 0
    assert manifest["omitted_files"] == 1


def test_bundle_logged(tmp_path: Path, reviewer_env: dict[str, str]) -> None:
    diff_text = (
        _build_diff_hunk("src/app.py", "print('app')")
        + _build_diff_hunk("package-lock.json", '{"name":"demo"}')
    )
    result, _, _ = _run_reviewer(diff_text, tmp_path, reviewer_env)

    assert "Context bundle:" in result.stdout


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


def test_summary_in_prompt(
    tmp_path: Path, reviewer_env: dict[str, str]
) -> None:
    """The prompt should contain the bundle summary inline."""
    diff_text = _build_diff_hunk("src/app.py", "print('app')")
    _, prompt_text, _ = _run_reviewer(diff_text, tmp_path, reviewer_env)

    # Summary should be in the prompt (file list, counts)
    assert "1 files changed" in prompt_text
    assert "src/app.py" in prompt_text
