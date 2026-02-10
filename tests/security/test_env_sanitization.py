"""Verify the reviewer runtime sanitizes its environment.

The opencode process must NOT see secrets that aren't explicitly
allowlisted (OPENROUTER_API_KEY).  This test uses a stub opencode
binary that fails if it detects any leaked variable.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
RUN_REVIEWER = REPO_ROOT / "scripts" / "run-reviewer.sh"

# Variables that MUST NOT leak into the opencode process.
DANGEROUS_VARS = [
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "ACTIONS_RUNTIME_TOKEN",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
    "AWS_SECRET_ACCESS_KEY",
    "CERBERUS_LEAK_CANARY",
]


def _make_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _make_env(bin_dir: Path, diff_file: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["CERBERUS_ROOT"] = str(REPO_ROOT)
    env["GH_DIFF_FILE"] = str(diff_file)
    env["OPENROUTER_API_KEY"] = "test-key-not-real"
    env["OPENCODE_MAX_STEPS"] = "5"
    env["REVIEW_TIMEOUT"] = "5"
    # Inject dangerous vars into the PARENT env.
    for var in DANGEROUS_VARS:
        env[var] = f"LEAKED_{var}"
    return env


def _write_env_checking_opencode(path: Path) -> None:
    """Stub opencode that fails if any dangerous var is visible."""
    checks = "\n".join(
        f'if [ -n "${{{v}:-}}" ]; then echo "LEAK:{v}" >&2; exit 99; fi'
        for v in DANGEROUS_VARS
    )
    _make_executable(
        path,
        f"#!/usr/bin/env bash\n"
        f"{checks}\n"
        f"cat <<'REVIEW'\n"
        f"```json\n"
        f'{{"reviewer":"STUB","perspective":"security","verdict":"PASS",'
        f'"confidence":0.95,"summary":"Env clean",'
        f'"findings":[],"stats":{{"files_reviewed":1,"files_with_issues":0,'
        f'"critical":0,"major":0,"minor":0,"info":0}}}}\n'
        f"```\n"
        f"REVIEW\n",
    )


def test_dangerous_vars_not_leaked_to_opencode(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_env_checking_opencode(bin_dir / "opencode")

    diff_file = tmp_path / "diff.patch"
    diff_file.write_text("diff --git a/f.py b/f.py\n+pass\n")

    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=_make_env(bin_dir, diff_file),
        capture_output=True,
        text=True,
        timeout=30,
    )
    # If any LEAK:<var> appeared, the stub exited 99 and the review fails.
    for var in DANGEROUS_VARS:
        assert f"LEAK:{var}" not in result.stderr, f"{var} leaked into opencode env"
    assert result.returncode == 0


def test_openrouter_api_key_is_forwarded(tmp_path: Path) -> None:
    """The API key MUST be forwarded — otherwise the review can't run."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_executable(
        bin_dir / "opencode",
        "#!/usr/bin/env bash\n"
        'if [ -z "${OPENROUTER_API_KEY:-}" ]; then\n'
        "  echo 'MISSING_KEY' >&2; exit 99\n"
        "fi\n"
        "cat <<'REVIEW'\n"
        "```json\n"
        '{"reviewer":"STUB","perspective":"security","verdict":"PASS",'
        '"confidence":0.95,"summary":"Key present",'
        '"findings":[],"stats":{"files_reviewed":1,"files_with_issues":0,'
        '"critical":0,"major":0,"minor":0,"info":0}}\n'
        "```\n"
        "REVIEW\n",
    )

    diff_file = tmp_path / "diff.patch"
    diff_file.write_text("diff --git a/f.py b/f.py\n+pass\n")

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["CERBERUS_ROOT"] = str(REPO_ROOT)
    env["GH_DIFF_FILE"] = str(diff_file)
    env["OPENROUTER_API_KEY"] = "test-key-not-real"
    env["OPENCODE_MAX_STEPS"] = "5"
    env["REVIEW_TIMEOUT"] = "5"

    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert "MISSING_KEY" not in result.stderr
    assert result.returncode == 0
