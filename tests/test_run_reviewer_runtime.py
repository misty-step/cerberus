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
    suffixes = (
        "parse-input", "output.txt", "stderr.log", "exitcode", "review.md",
        "timeout-marker.txt", "fast-path-prompt.md", "fast-path-output.txt",
        "fast-path-stderr.log", "model-used",
        "primary-model", "configured-model",
    )
    for perspective in PERSPECTIVES:
        for suffix in suffixes:
            Path(f"/tmp/{perspective}-{suffix}").unlink(missing_ok=True)
    yield
    for perspective in PERSPECTIVES:
        for suffix in suffixes:
            Path(f"/tmp/{perspective}-{suffix}").unlink(missing_ok=True)


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


def write_fake_cerberus_root(
    root: Path,
    *,
    perspective: str = "security",
    config_yml: str | None = None,
) -> None:
    (root / "defaults").mkdir(parents=True)
    (root / "templates").mkdir(parents=True)
    (root / "scripts" / "lib").mkdir(parents=True)
    (root / ".opencode" / "agents").mkdir(parents=True)

    if config_yml is None:
        config_yml = "\n".join(["- name: SENTINEL", f"  perspective: {perspective}", ""])
    (root / "defaults" / "config.yml").write_text(config_yml)
    (root / "templates" / "review-prompt.md").write_text("{{DIFF_FILE}}\n{{PERSPECTIVE}}\n")
    # Keep fake CERBERUS_ROOT runnable as action code evolves.
    (root / "scripts" / "render-review-prompt.py").write_text(
        (REPO_ROOT / "scripts" / "render-review-prompt.py").read_text()
    )
    (root / "scripts" / "lib" / "__init__.py").write_text(
        (REPO_ROOT / "scripts" / "lib" / "__init__.py").read_text()
    )
    (root / "scripts" / "lib" / "review_prompt.py").write_text(
        (REPO_ROOT / "scripts" / "lib" / "review_prompt.py").read_text()
    )
    (root / "scripts" / "lib" / "prompt_sanitize.py").write_text(
        (REPO_ROOT / "scripts" / "lib" / "prompt_sanitize.py").read_text()
    )
    (root / "opencode.json").write_text("CERBERUS_OPENCODE_JSON\n")
    (root / ".opencode" / "agents" / f"{perspective}.md").write_text("CERBERUS_AGENT\n")


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


def test_fast_path_fallback_runs_on_timeout_with_no_output(tmp_path: Path) -> None:
    """When primary times out with no output and fast-path succeeds, use fast-path."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    call_counter = tmp_path / "call-count"
    call_counter.write_text("0")

    # First call (primary): stubs a timeout exit; second call (fast-path): returns JSON.
    make_executable(
        bin_dir / "opencode",
        (
            "#!/usr/bin/env bash\n"
            "count=$(cat '" + str(call_counter) + "')\n"
            "count=$((count + 1))\n"
            "printf '%s' \"$count\" > '" + str(call_counter) + "'\n"
            "if [[ \"$count\" -eq 1 ]]; then\n"
            "  exit 0\n"  # Primary produces no output (empty stdout, no scratchpad)
            "fi\n"
            "cat <<'REVIEW'\n"
            "```json\n"
            '{"reviewer":"SENTINEL","perspective":"security","verdict":"PASS",'
            '"confidence":0.80,"summary":"Fast-path review",'
            '"findings":[],"stats":{"files_reviewed":1,"files_with_issues":0,'
            '"critical":0,"major":0,"minor":0,"info":0}}\n'
            "```\n"
            "REVIEW\n"
        ),
    )

    # Stub timeout to simulate exit code 124 on the first invocation.
    make_executable(
        bin_dir / "timeout",
        (
            "#!/usr/bin/env bash\n"
            "budget=\"$1\"; shift\n"
            "count=$(cat '" + str(call_counter) + "')\n"
            "if [[ \"$count\" -eq 0 ]]; then\n"
            "  \"$@\"\n"  # Run primary — opencode writes nothing
            "  exit 124\n"  # Simulate timeout
            "fi\n"
            "\"$@\"\n"  # Fast-path: run normally
        ),
    )

    diff_file = tmp_path / "diff.patch"
    diff_file.write_text(
        "diff --git a/app.py b/app.py\n"
        "+print('hello')\n"
        "diff --git a/utils.py b/utils.py\n"
        "+pass\n"
    )

    env = make_env(bin_dir, diff_file)
    env["REVIEW_TIMEOUT"] = "600"
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "fast-path fallback" in result.stdout.lower()
    assert "parse-input: fast-path output" in result.stdout
    parse_input_ref = Path("/tmp/security-parse-input")
    assert parse_input_ref.exists()
    parse_file = Path(parse_input_ref.read_text().strip())
    assert "```json" in parse_file.read_text()


def test_fast_path_also_fails_produces_enriched_timeout_marker(tmp_path: Path) -> None:
    """When both primary and fast-path time out, write enriched timeout marker."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    # opencode always produces empty output
    make_executable(bin_dir / "opencode", "#!/usr/bin/env bash\nexit 0\n")
    # timeout always returns 124
    make_executable(
        bin_dir / "timeout",
        "#!/usr/bin/env bash\nshift; \"$@\"; exit 124\n",
    )

    diff_file = tmp_path / "diff.patch"
    diff_file.write_text(
        "diff --git a/src/main.py b/src/main.py\n"
        "+import os\n"
    )

    env = make_env(bin_dir, diff_file)
    env["REVIEW_TIMEOUT"] = "600"
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "parse-input: timeout marker" in result.stdout
    parse_input_ref = Path("/tmp/security-parse-input")
    parse_file = Path(parse_input_ref.read_text().strip())
    content = parse_file.read_text()
    assert "Review Timeout:" in content
    assert "Files in diff:" in content
    assert "src/main.py" in content
    assert "Fast-path: yes" in content
    assert "Next steps:" in content


def test_short_timeout_skips_fast_path(tmp_path: Path) -> None:
    """With timeout < 120s, fast-path is skipped (budget too small)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    make_executable(bin_dir / "opencode", "#!/usr/bin/env bash\nexit 0\n")
    make_executable(
        bin_dir / "timeout",
        "#!/usr/bin/env bash\nshift; \"$@\"; exit 124\n",
    )

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)

    env = make_env(bin_dir, diff_file)
    env["REVIEW_TIMEOUT"] = "60"  # Too short for fast-path (budget = 12 < 60)
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "fast-path fallback" not in result.stdout.lower()
    assert "parse-input: timeout marker" in result.stdout
    parse_input_ref = Path("/tmp/security-parse-input")
    parse_file = Path(parse_input_ref.read_text().strip())
    content = parse_file.read_text()
    assert "Review Timeout:" in content
    assert "Fast-path: no" in content


# --- Primary model selection precedence ---


def test_primary_model_uses_reviewer_model_when_input_empty(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_stub_opencode(bin_dir / "opencode")

    cerberus_root = tmp_path / "cerberus-root"
    write_fake_cerberus_root(
        cerberus_root,
        perspective="security",
        config_yml="\n".join(
            [
                "version: 1",
                "model:",
                '  default: "openrouter/default-model"',
                "reviewers:",
                "  - name: SENTINEL",
                "    perspective: security",
                '    model: "openrouter/reviewer-model"',
                "",
            ]
        ),
    )

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    env = make_env_with_cerberus_root(bin_dir, diff_file, cerberus_root)
    env.pop("OPENCODE_MODEL", None)
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    primary_model = Path("/tmp/security-primary-model").read_text().strip()
    assert primary_model == "openrouter/reviewer-model"


def test_primary_model_input_overrides_reviewer_model(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_stub_opencode(bin_dir / "opencode")

    cerberus_root = tmp_path / "cerberus-root"
    write_fake_cerberus_root(
        cerberus_root,
        perspective="security",
        config_yml="\n".join(
            [
                "version: 1",
                "model:",
                '  default: "openrouter/default-model"',
                "reviewers:",
                "  - name: SENTINEL",
                "    perspective: security",
                '    model: "openrouter/reviewer-model"',
                "",
            ]
        ),
    )

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    env = make_env_with_cerberus_root(bin_dir, diff_file, cerberus_root)
    env["OPENCODE_MODEL"] = "openrouter/input-model"
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    primary_model = Path("/tmp/security-primary-model").read_text().strip()
    assert primary_model == "openrouter/input-model"


def test_primary_model_uses_config_default_when_reviewer_model_missing(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_stub_opencode(bin_dir / "opencode")

    cerberus_root = tmp_path / "cerberus-root"
    write_fake_cerberus_root(
        cerberus_root,
        perspective="security",
        config_yml="\n".join(
            [
                "version: 1",
                "model:",
                '  default: "openrouter/default-model"',
                "reviewers:",
                "  - name: SENTINEL",
                "    perspective: security",
                "",
            ]
        ),
    )

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    env = make_env_with_cerberus_root(bin_dir, diff_file, cerberus_root)
    env.pop("OPENCODE_MODEL", None)
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    primary_model = Path("/tmp/security-primary-model").read_text().strip()
    assert primary_model == "openrouter/default-model"


def test_primary_model_ignores_whitespace_only_input_model(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_stub_opencode(bin_dir / "opencode")

    cerberus_root = tmp_path / "cerberus-root"
    write_fake_cerberus_root(
        cerberus_root,
        perspective="security",
        config_yml="\n".join(
            [
                "version: 1",
                "model:",
                '  default: "openrouter/default-model"',
                "reviewers:",
                "  - name: SENTINEL",
                "    perspective: security",
                '    model: "openrouter/reviewer-model"',
                "",
            ]
        ),
    )

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    env = make_env_with_cerberus_root(bin_dir, diff_file, cerberus_root)
    env["OPENCODE_MODEL"] = "   "
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    primary_model = Path("/tmp/security-primary-model").read_text().strip()
    assert primary_model == "openrouter/reviewer-model"


def test_primary_model_strips_quotes_in_input_model(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_stub_opencode(bin_dir / "opencode")

    cerberus_root = tmp_path / "cerberus-root"
    write_fake_cerberus_root(
        cerberus_root,
        perspective="security",
        config_yml="\n".join(
            [
                "version: 1",
                "model:",
                '  default: "openrouter/default-model"',
                "reviewers:",
                "  - name: SENTINEL",
                "    perspective: security",
                "",
            ]
        ),
    )

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    env = make_env_with_cerberus_root(bin_dir, diff_file, cerberus_root)
    env["OPENCODE_MODEL"] = '"openrouter/input-model"'
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    primary_model = Path("/tmp/security-primary-model").read_text().strip()
    assert primary_model == "openrouter/input-model"


def test_primary_model_ignores_empty_reviewer_model_uses_config_default(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_stub_opencode(bin_dir / "opencode")

    cerberus_root = tmp_path / "cerberus-root"
    write_fake_cerberus_root(
        cerberus_root,
        perspective="security",
        config_yml="\n".join(
            [
                "version: 1",
                "model:",
                '  default: "openrouter/default-model"',
                "reviewers:",
                "  - name: SENTINEL",
                "    perspective: security",
                '    model: ""',
                "",
            ]
        ),
    )

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    env = make_env_with_cerberus_root(bin_dir, diff_file, cerberus_root)
    env.pop("OPENCODE_MODEL", None)
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    primary_model = Path("/tmp/security-primary-model").read_text().strip()
    assert primary_model == "openrouter/default-model"


def test_primary_model_uses_reviewer_model_regardless_of_field_order(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_stub_opencode(bin_dir / "opencode")

    cerberus_root = tmp_path / "cerberus-root"
    write_fake_cerberus_root(
        cerberus_root,
        perspective="security",
        config_yml="\n".join(
            [
                "version: 1",
                "model:",
                '  default: "openrouter/default-model"',
                "reviewers:",
                "  - name: SENTINEL",
                '    model: "openrouter/reviewer-model"',
                "    perspective: security",
                "",
            ]
        ),
    )

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    env = make_env_with_cerberus_root(bin_dir, diff_file, cerberus_root)
    env.pop("OPENCODE_MODEL", None)
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    primary_model = Path("/tmp/security-primary-model").read_text().strip()
    assert primary_model == "openrouter/reviewer-model"


def test_primary_model_hardcoded_default_when_config_has_no_model_section(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_stub_opencode(bin_dir / "opencode")

    cerberus_root = tmp_path / "cerberus-root"
    write_fake_cerberus_root(
        cerberus_root,
        perspective="security",
        config_yml="\n".join(
            [
                "version: 1",
                "reviewers:",
                "  - name: SENTINEL",
                "    perspective: security",
                "",
            ]
        ),
    )

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    env = make_env_with_cerberus_root(bin_dir, diff_file, cerberus_root)
    env.pop("OPENCODE_MODEL", None)
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    primary_model = Path("/tmp/security-primary-model").read_text().strip()
    assert primary_model == "openrouter/moonshotai/kimi-k2.5"


# --- Model fallback tests ---


def test_fallback_model_used_after_primary_transient_failure(tmp_path: Path) -> None:
    """When primary model exhausts retries with transient errors, fallback model is tried."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    attempt_counter = tmp_path / "attempt-count"
    attempt_counter.write_text("0")

    # opencode stub: first 4 calls fail (primary: 1 + 3 retries), 5th succeeds (fallback).
    make_executable(
        bin_dir / "opencode",
        (
            "#!/usr/bin/env bash\n"
            "count=$(cat '" + str(attempt_counter) + "')\n"
            "count=$((count + 1))\n"
            "printf '%s' \"$count\" > '" + str(attempt_counter) + "'\n"
            "if [[ \"$count\" -le 4 ]]; then\n"
            "  echo 'HTTP 500 Internal Server Error' >&2\n"
            "  exit 1\n"
            "fi\n"
            "cat <<'REVIEW'\n"
            "```json\n"
            '{"reviewer":"STUB","perspective":"security","verdict":"PASS",'
            '"confidence":0.95,"summary":"Fallback succeeded",'
            '"findings":[],"stats":{"files_reviewed":1,"files_with_issues":0,'
            '"critical":0,"major":0,"minor":0,"info":0}}\n'
            "```\n"
            "REVIEW\n"
        ),
    )
    make_executable(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 0\n")

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    env = make_env(bin_dir, diff_file)
    env["CERBERUS_FALLBACK_MODELS"] = "openrouter/anthropic/claude-sonnet-4-5"
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0
    assert "Falling back to model:" in result.stdout
    assert "openrouter/anthropic/claude-sonnet-4-5" in result.stdout
    assert "model_used=openrouter/anthropic/claude-sonnet-4-5" in result.stdout
    model_used = Path("/tmp/security-model-used").read_text().strip()
    assert model_used == "openrouter/anthropic/claude-sonnet-4-5"


def test_primary_succeeds_no_fallback_triggered(tmp_path: Path) -> None:
    """When primary model succeeds, no fallback is attempted."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_stub_opencode(bin_dir / "opencode")

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    env = make_env(bin_dir, diff_file)
    env["CERBERUS_FALLBACK_MODELS"] = "openrouter/anthropic/claude-sonnet-4-5"
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "Falling back to model:" not in result.stdout
    primary_model = Path("/tmp/security-primary-model").read_text().strip()
    model_used = Path("/tmp/security-model-used").read_text().strip()
    assert model_used == primary_model


def test_all_models_fail_writes_error_verdict(tmp_path: Path) -> None:
    """When all models fail with transient errors, write error verdict."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_executable(
        bin_dir / "opencode",
        (
            "#!/usr/bin/env bash\n"
            "echo 'HTTP 500 Internal Server Error' >&2\n"
            "exit 1\n"
        ),
    )
    make_executable(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 0\n")

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    env = make_env(bin_dir, diff_file)
    env["CERBERUS_FALLBACK_MODELS"] = "openrouter/fallback-model"
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0
    parse_input_ref = Path("/tmp/security-parse-input")
    assert parse_input_ref.exists()
    parse_file = Path(parse_input_ref.read_text().strip())
    content = parse_file.read_text()
    assert "API Error:" in content
    assert "Models tried:" in content


def test_auth_error_skips_fallback(tmp_path: Path) -> None:
    """Auth/quota permanent errors do NOT trigger model fallback."""
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
            "echo '401 incorrect_api_key' >&2\n"
            "exit 1\n"
        ),
    )

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    env = make_env(bin_dir, diff_file)
    env["CERBERUS_FALLBACK_MODELS"] = "openrouter/fallback-model"
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    # Should NOT have fallen back — auth error is the same API key for all models.
    assert attempt_counter.read_text() == "1"
    assert "Falling back to model:" not in result.stdout
    parse_input_ref = Path("/tmp/security-parse-input")
    parse_file = Path(parse_input_ref.read_text().strip())
    content = parse_file.read_text()
    assert "API Error: API_KEY_INVALID" in content


def test_client_4xx_triggers_fallback(tmp_path: Path) -> None:
    """Non-auth 4xx errors (e.g., model not found) trigger model fallback."""
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
            "if [[ \"$count\" -eq 1 ]]; then\n"
            "  echo 'HTTP 404 Not Found: model does not exist' >&2\n"
            "  exit 1\n"
            "fi\n"
            "cat <<'REVIEW'\n"
            "```json\n"
            '{"reviewer":"STUB","perspective":"security","verdict":"PASS",'
            '"confidence":0.95,"summary":"Fallback model worked",'
            '"findings":[],"stats":{"files_reviewed":1,"files_with_issues":0,'
            '"critical":0,"major":0,"minor":0,"info":0}}\n'
            "```\n"
            "REVIEW\n"
        ),
    )

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    env = make_env(bin_dir, diff_file)
    env["CERBERUS_FALLBACK_MODELS"] = "openrouter/fallback-model"
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "Falling back to model:" in result.stdout
    model_used = Path("/tmp/security-model-used").read_text().strip()
    assert model_used == "openrouter/fallback-model"


def test_no_fallback_models_behaves_same_as_before(tmp_path: Path) -> None:
    """When CERBERUS_FALLBACK_MODELS is empty, behavior matches original (no fallback)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_executable(
        bin_dir / "opencode",
        (
            "#!/usr/bin/env bash\n"
            "echo 'HTTP 500 Internal Server Error' >&2\n"
            "exit 1\n"
        ),
    )
    make_executable(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 0\n")

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    env = make_env(bin_dir, diff_file)
    # No CERBERUS_FALLBACK_MODELS set
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0
    assert "Falling back to model:" not in result.stdout
    primary_model = Path("/tmp/security-primary-model").read_text().strip()
    model_used = Path("/tmp/security-model-used").read_text().strip()
    assert model_used == primary_model


# --- Provider generic error / empty output / unknown error tests ---


def test_provider_returned_error_is_retried(tmp_path: Path) -> None:
    """'Provider returned error' from OpenCode wrapper is treated as transient."""
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
            "  echo 'Error: Provider returned error' >&2\n"
            "  exit 1\n"
            "fi\n"
            "cat <<'REVIEW'\n"
            "```json\n"
            '{"reviewer":"STUB","perspective":"security","verdict":"PASS",'
            '"confidence":0.95,"summary":"Recovered from provider error",'
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
    assert "Retrying after transient error (class=provider_generic)" in result.stdout


def test_empty_output_on_exit_zero_triggers_retry(tmp_path: Path) -> None:
    """Exit 0 with no output is not accepted as success — retries instead."""
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
            "  exit 0\n"  # Empty output, exit 0
            "fi\n"
            "cat <<'REVIEW'\n"
            "```json\n"
            '{"reviewer":"STUB","perspective":"security","verdict":"PASS",'
            '"confidence":0.95,"summary":"Second attempt succeeded",'
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
    assert "opencode exited 0 but produced no output" in result.stdout
    parse_input_ref = Path("/tmp/security-parse-input")
    assert parse_input_ref.exists()
    parse_file = Path(parse_input_ref.read_text().strip())
    assert "```json" in parse_file.read_text()


def test_unknown_error_tries_fallback_model(tmp_path: Path) -> None:
    """Unrecognized error from primary model tries fallback instead of aborting."""
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
            "if [[ \"$count\" -eq 1 ]]; then\n"
            "  echo 'Unexpected internal failure: segfault in wasm runtime' >&2\n"
            "  exit 1\n"
            "fi\n"
            "cat <<'REVIEW'\n"
            "```json\n"
            '{"reviewer":"STUB","perspective":"security","verdict":"PASS",'
            '"confidence":0.95,"summary":"Fallback after unknown error",'
            '"findings":[],"stats":{"files_reviewed":1,"files_with_issues":0,'
            '"critical":0,"major":0,"minor":0,"info":0}}\n'
            "```\n"
            "REVIEW\n"
        ),
    )

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    env = make_env(bin_dir, diff_file)
    env["CERBERUS_FALLBACK_MODELS"] = "openrouter/fallback-model"
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "Unknown error type" in result.stdout
    assert "Falling back to model:" in result.stdout
    model_used = Path("/tmp/security-model-used").read_text().strip()
    assert model_used == "openrouter/fallback-model"


def test_empty_output_exhausts_retries_then_uses_fallback(tmp_path: Path) -> None:
    """Empty output on exit 0 retries, then falls back to next model (not unbound var)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    attempt_counter = tmp_path / "attempt-count"
    attempt_counter.write_text("0")

    # Primary model (attempts 1-4): always empty output.
    # Fallback model (attempt 5): returns valid JSON.
    make_executable(
        bin_dir / "opencode",
        (
            "#!/usr/bin/env bash\n"
            "count=$(cat '" + str(attempt_counter) + "')\n"
            "count=$((count + 1))\n"
            "printf '%s' \"$count\" > '" + str(attempt_counter) + "'\n"
            "if [[ \"$count\" -le 4 ]]; then\n"
            "  exit 0\n"  # Empty output, exit 0
            "fi\n"
            "cat <<'REVIEW'\n"
            "```json\n"
            '{"reviewer":"STUB","perspective":"security","verdict":"PASS",'
            '"confidence":0.95,"summary":"Fallback succeeded after empty primary",'
            '"findings":[],"stats":{"files_reviewed":1,"files_with_issues":0,'
            '"critical":0,"major":0,"minor":0,"info":0}}\n'
            "```\n"
            "REVIEW\n"
        ),
    )
    make_executable(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 0\n")

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    env = make_env(bin_dir, diff_file)
    env["CERBERUS_FALLBACK_MODELS"] = "openrouter/fallback-model"
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0
    assert "Falling back to model:" in result.stdout
    assert "opencode exited 0 but produced no output" in result.stdout
    model_used = Path("/tmp/security-model-used").read_text().strip()
    assert model_used == "openrouter/fallback-model"
