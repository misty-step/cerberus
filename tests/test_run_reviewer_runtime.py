"""Behavior tests for scripts/run-reviewer.sh runtime paths."""

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
RUN_REVIEWER = REPO_ROOT / "scripts" / "run-reviewer.sh"
PERSPECTIVES = (
    "correctness",
    "architecture",
    "security",
    "performance",
    "maintainability",
)


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


def write_stub_opencode(path: Path, verdict: str = "PASS") -> None:
    make_executable(
        path,
        (
            "#!/usr/bin/env bash\n"
            "cat <<'REVIEW'\n"
            "```json\n"
            '{"reviewer":"STUB","perspective":"security","verdict":"'
            + verdict
            + '","confidence":0.95,"summary":"Stub output",'
              '"findings":[],"stats":{"files_reviewed":1,"files_with_issues":0,'
              '"critical":0,"major":0,"minor":0,"info":0}}\n'
            "```\n"
            "REVIEW\n"
        ),
    )


def write_simple_diff(path: Path) -> None:
    path.write_text("diff --git a/app.py b/app.py\n+print('hello')\n")


@pytest.fixture(autouse=True)
def cleanup_tmp_outputs() -> None:
    """Keep /tmp artifacts from one test from leaking into others."""
    import shutil
    suffixes = ("parse-input", "output.txt", "stderr.log", "exitcode", "review.md", "timeout-marker.txt")
    for perspective in PERSPECTIVES:
        for suffix in suffixes:
            Path(f"/tmp/{perspective}-{suffix}").unlink(missing_ok=True)
        context_dir = Path(f"/tmp/cerberus-context-{perspective}")
        if context_dir.exists():
            shutil.rmtree(context_dir, ignore_errors=True)
    yield
    for perspective in PERSPECTIVES:
        for suffix in suffixes:
            Path(f"/tmp/{perspective}-{suffix}").unlink(missing_ok=True)
        context_dir = Path(f"/tmp/cerberus-context-{perspective}")
        if context_dir.exists():
            shutil.rmtree(context_dir, ignore_errors=True)


def test_empty_diff_file_is_handled(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_stub_opencode(bin_dir / "opencode")

    diff_file = tmp_path / "empty.diff"
    diff_file.write_text("")

    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=make_env(bin_dir, diff_file),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    parse_input_ref = Path("/tmp/security-parse-input")
    assert parse_input_ref.exists()
    parse_file = Path(parse_input_ref.read_text().strip())
    assert parse_file.exists()
    assert "```json" in parse_file.read_text()

def make_env_with_cerberus_root(bin_dir: Path, diff_file: Path, cerberus_root: Path) -> dict[str, str]:
    env = make_env(bin_dir, diff_file)
    env["CERBERUS_ROOT"] = str(cerberus_root)
    return env


def write_fake_cerberus_root(root: Path, perspective: str = "security") -> None:
    (root / "defaults").mkdir(parents=True)
    (root / "templates").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    (root / ".opencode" / "agents").mkdir(parents=True)

    (root / "defaults" / "config.yml").write_text(
        "\n".join(
            [
                "- name: SENTINEL",
                f"  perspective: {perspective}",
                "",
            ]
        )
    )
    (root / "templates" / "review-prompt.md").write_text(
        "{{BUNDLE_SUMMARY}}\n{{CONTEXT_BUNDLE_DIR}}\n{{PERSPECTIVE}}\n"
    )
    (root / "opencode.json").write_text("CERBERUS_OPENCODE_JSON\n")
    (root / ".opencode" / "agents" / f"{perspective}.md").write_text("CERBERUS_AGENT\n")

    # Copy build-context.py from the real repo so run-reviewer.sh can invoke it
    import shutil
    real_script = REPO_ROOT / "scripts" / "build-context.py"
    shutil.copy2(real_script, root / "scripts" / "build-context.py")


def test_stages_trusted_opencode_config_then_restores_workspace(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    cerberus_root = tmp_path / "cerberus-root"
    write_fake_cerberus_root(cerberus_root, perspective="security")

    # Workspace contains attacker-controlled config that must not be used.
    (tmp_path / "opencode.json").write_text("WORKSPACE_OPENCODE_JSON\n")
    (tmp_path / ".opencode" / "agents").mkdir(parents=True)
    (tmp_path / ".opencode" / "agents" / "security.md").write_text("WORKSPACE_AGENT\n")

    make_executable(
        bin_dir / "opencode",
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "if [[ \"$(cat opencode.json)\" != \"CERBERUS_OPENCODE_JSON\" ]]; then\n"
            "  echo 'expected staged opencode.json' >&2\n"
            "  exit 2\n"
            "fi\n"
            "if [[ \"$(cat .opencode/agents/security.md)\" != \"CERBERUS_AGENT\" ]]; then\n"
            "  echo 'expected staged agent file' >&2\n"
            "  exit 2\n"
            "fi\n"
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

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)

    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=make_env_with_cerberus_root(bin_dir, diff_file, cerberus_root),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert (tmp_path / "opencode.json").read_text() == "WORKSPACE_OPENCODE_JSON\n"
    assert (tmp_path / ".opencode" / "agents" / "security.md").read_text() == "WORKSPACE_AGENT\n"


def test_binary_diff_file_is_handled(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_stub_opencode(bin_dir / "opencode")

    diff_file = tmp_path / "binary.diff"
    diff_file.write_text(
        "diff --git a/logo.png b/logo.png\n"
        "new file mode 100644\n"
        "index 0000000..1234567\n"
        "Binary files /dev/null and b/logo.png differ\n"
    )

    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=make_env(bin_dir, diff_file),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "parse-input:" in result.stdout


def test_unknown_perspective_fails_fast(tmp_path: Path) -> None:
    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)

    env = os.environ.copy()
    env["CERBERUS_ROOT"] = str(REPO_ROOT)
    env["GH_DIFF_FILE"] = str(diff_file)

    result = subprocess.run(
        [str(RUN_REVIEWER), "ghost"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
    assert "missing agent file" in result.stderr


def test_transient_server_error_retries_then_succeeds(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    retry_counter = tmp_path / "retry-count"
    retry_counter.write_text("0")

    make_executable(
        bin_dir / "opencode",
        (
            "#!/usr/bin/env bash\n"
            "count=$(cat '" + str(retry_counter) + "')\n"
            "count=$((count + 1))\n"
            "printf '%s' \"$count\" > '" + str(retry_counter) + "'\n"
            "if [[ \"$count\" -eq 1 ]]; then\n"
            "  echo 'HTTP 500 Internal Server Error' >&2\n"
            "  exit 1\n"
            "fi\n"
            "cat <<'REVIEW'\n"
            "```json\n"
            '{"reviewer":"STUB","perspective":"security","verdict":"PASS",'
              '"confidence":0.95,"summary":"Recovered",'
              '"findings":[],"stats":{"files_reviewed":1,"files_with_issues":0,'
              '"critical":0,"major":0,"minor":0,"info":0}}\n'
            "```\n"
            "REVIEW\n"
        ),
    )
    make_executable(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 0\n")

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=make_env(bin_dir, diff_file),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert retry_counter.read_text() == "2"
    assert "Retrying after transient error (class=server_5xx)" in result.stdout


def test_transient_network_error_retries_then_succeeds(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    retry_counter = tmp_path / "retry-count"
    retry_counter.write_text("0")

    make_executable(
        bin_dir / "opencode",
        (
            "#!/usr/bin/env bash\n"
            "count=$(cat '" + str(retry_counter) + "')\n"
            "count=$((count + 1))\n"
            "printf '%s' \"$count\" > '" + str(retry_counter) + "'\n"
            "if [[ \"$count\" -eq 1 ]]; then\n"
            "  echo 'network timeout while connecting to provider' >&2\n"
            "  exit 1\n"
            "fi\n"
            "cat <<'REVIEW'\n"
            "```json\n"
            '{"reviewer":"STUB","perspective":"security","verdict":"PASS",'
              '"confidence":0.95,"summary":"Recovered",'
              '"findings":[],"stats":{"files_reviewed":1,"files_with_issues":0,'
              '"critical":0,"major":0,"minor":0,"info":0}}\n'
            "```\n"
            "REVIEW\n"
        ),
    )
    make_executable(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 0\n")

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=make_env(bin_dir, diff_file),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert retry_counter.read_text() == "2"
    assert "Retrying after transient error (class=network)" in result.stdout


def test_rate_limit_retry_after_header_overrides_default_backoff(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    retry_counter = tmp_path / "retry-count"
    retry_counter.write_text("0")
    sleep_arg_file = tmp_path / "sleep-arg"
    sleep_arg_file.write_text("")

    make_executable(
        bin_dir / "opencode",
        (
            "#!/usr/bin/env bash\n"
            "count=$(cat '" + str(retry_counter) + "')\n"
            "count=$((count + 1))\n"
            "printf '%s' \"$count\" > '" + str(retry_counter) + "'\n"
            "if [[ \"$count\" -eq 1 ]]; then\n"
            "  echo 'HTTP 429 Too Many Requests' >&2\n"
            "  echo 'Retry-After: 9' >&2\n"
            "  exit 1\n"
            "fi\n"
            "cat <<'REVIEW'\n"
            "```json\n"
            '{"reviewer":"STUB","perspective":"security","verdict":"PASS",'
              '"confidence":0.95,"summary":"Recovered",'
              '"findings":[],"stats":{"files_reviewed":1,"files_with_issues":0,'
              '"critical":0,"major":0,"minor":0,"info":0}}\n'
            "```\n"
            "REVIEW\n"
        ),
    )
    make_executable(
        bin_dir / "sleep",
        "#!/usr/bin/env bash\n"
        "echo \"$1\" > '" + str(sleep_arg_file) + "'\n"
        "exit 0\n",
    )

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=make_env(bin_dir, diff_file),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert retry_counter.read_text() == "2"
    assert sleep_arg_file.read_text() == "9\n"
    assert "Retrying after transient error (class=rate_limit)" in result.stdout
    assert "wait=9s" in result.stdout


def test_permanent_api_error_is_written_for_parser(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_executable(
        bin_dir / "opencode",
        (
            "#!/usr/bin/env bash\n"
            "echo '401 incorrect_api_key' >&2\n"
            "exit 1\n"
        ),
    )

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=make_env(bin_dir, diff_file),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    parse_input_ref = Path("/tmp/security-parse-input")
    assert parse_input_ref.exists()
    parse_file = Path(parse_input_ref.read_text().strip())
    content = parse_file.read_text()
    assert "API Error: API_KEY_INVALID" in content


def test_non_transient_4xx_error_does_not_retry(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    attempt_counter = tmp_path / "attempt-count"
    attempt_counter.write_text("0")

    make_executable(
        bin_dir / "opencode",
        (
            "#!/usr/bin/env bash\n"
            "count=$(cat '" + str(attempt_counter) + "')\n"
            "count=$((count + 1))\n"
            "printf '%s' \"$count\" > '" + str(attempt_counter) + "'\n"
            "echo 'HTTP 404 Not Found' >&2\n"
            "exit 1\n"
        ),
    )
    make_executable(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 99\n")

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=make_env(bin_dir, diff_file),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert attempt_counter.read_text() == "1"
    assert "Retrying after transient error" not in result.stdout
    parse_input_ref = Path("/tmp/security-parse-input")
    assert parse_input_ref.exists()
    parse_file = Path(parse_input_ref.read_text().strip())
    content = parse_file.read_text()
    assert "API Error: API_ERROR" in content


def test_timeout_with_partial_output_exits_zero(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_stub_opencode(bin_dir / "opencode")
    make_executable(
        bin_dir / "timeout",
        (
            "#!/usr/bin/env bash\n"
            "shift\n"
            "cat <<'OUT'\n"
            "## Investigation Notes\n"
            "Collected partial evidence before timeout.\n"
            "\n"
            "## Verdict: WARN\n"
            "OUT\n"
            "exit 124\n"
        ),
    )

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=make_env(bin_dir, diff_file),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "parse-input: stdout (timeout, partial review)" in result.stdout
    parse_input_ref = Path("/tmp/security-parse-input")
    assert parse_input_ref.exists()
    parse_file = Path(parse_input_ref.read_text().strip())
    assert parse_file == Path("/tmp/security-output.txt")
    content = parse_file.read_text()
    assert "## Investigation Notes" in content
    assert "## Verdict: WARN" in content
    assert "Review Timeout:" not in content


@pytest.mark.parametrize(
    "stderr_line",
    [
        "No cookie auth credentials found",
        "error: no credentials found for authentication",
        "No auth credentials available",
    ],
)
def test_auth_credential_errors_are_permanent_api_errors(tmp_path: Path, stderr_line: str) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    attempt_counter = tmp_path / "attempt-count"
    attempt_counter.write_text("0")

    make_executable(
        bin_dir / "opencode",
        (
            "#!/usr/bin/env bash\n"
            "count=$(cat '" + str(attempt_counter) + "')\n"
            "count=$((count + 1))\n"
            "printf '%s' \"$count\" > '" + str(attempt_counter) + "'\n"
            "echo '" + stderr_line + "' >&2\n"
            "exit 1\n"
        ),
    )

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=make_env(bin_dir, diff_file),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert attempt_counter.read_text() == "1"
    assert "Permanent API error detected. Writing error verdict." in result.stdout

    parse_input_ref = Path("/tmp/security-parse-input")
    assert parse_input_ref.exists()
    parse_file = Path(parse_input_ref.read_text().strip())
    content = parse_file.read_text()
    assert "API Error:" in content
    assert stderr_line in content
