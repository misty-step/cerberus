"""Behavior tests for scripts/run-reviewer.sh runtime paths (Pi runtime)."""

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
    env["CERBERUS_TMP"] = "/tmp"
    env["GH_DIFF_FILE"] = str(diff_file)
    env["OPENROUTER_API_KEY"] = "test-key-not-real"
    env["OPENCODE_MAX_STEPS"] = "5"
    env["REVIEW_TIMEOUT"] = "5"
    env["CERBERUS_TEST_NO_SLEEP"] = "1"
    env["CERBERUS_ALLOW_MISSING_REVIEWER_PROFILES"] = "1"
    return env


def write_stub_pi(path: Path, verdict: str = "PASS") -> None:
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
    suffixes = (
        "parse-input",
        "output.txt",
        "stderr.log",
        "exitcode",
        "review.md",
        "timeout-marker.txt",
        "fast-path-prompt.md",
        "fast-path-output.txt",
        "fast-path-stderr.log",
        "model-used",
        "primary-model",
        "configured-model",
        "parse-failure-models.txt",
        "parse-failure-retries.txt",
        "runtime-telemetry.ndjson",
    )
    for perspective in PERSPECTIVES:
        for suffix in suffixes:
            Path(f"/tmp/{perspective}-{suffix}").unlink(missing_ok=True)
    yield
    for perspective in PERSPECTIVES:
        for suffix in suffixes:
            Path(f"/tmp/{perspective}-{suffix}").unlink(missing_ok=True)


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
    (root / "scripts" / "read-defaults-config.py").write_text(
        (REPO_ROOT / "scripts" / "read-defaults-config.py").read_text()
    )
    (root / "scripts" / "render-review-prompt.py").write_text(
        (REPO_ROOT / "scripts" / "render-review-prompt.py").read_text()
    )
    (root / "scripts" / "lib" / "__init__.py").write_text(
        (REPO_ROOT / "scripts" / "lib" / "__init__.py").read_text()
    )
    (root / "scripts" / "lib" / "defaults_config.py").write_text(
        (REPO_ROOT / "scripts" / "lib" / "defaults_config.py").read_text()
    )
    (root / "scripts" / "lib" / "review_prompt.py").write_text(
        (REPO_ROOT / "scripts" / "lib" / "review_prompt.py").read_text()
    )
    (root / "scripts" / "lib" / "prompt_sanitize.py").write_text(
        (REPO_ROOT / "scripts" / "lib" / "prompt_sanitize.py").read_text()
    )
    (root / ".opencode" / "agents" / f"{perspective}.md").write_text("AGENT BODY\n")


def test_empty_diff_file_is_handled(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_stub_pi(bin_dir / "pi")

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


def test_binary_diff_file_is_handled(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_stub_pi(bin_dir / "pi")

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
    env["CERBERUS_TMP"] = "/tmp"
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
        bin_dir / "pi",
        (
            "#!/usr/bin/env bash\n"
            f"count=$(cat '{retry_counter}')\n"
            "count=$((count + 1))\n"
            f"printf '%s' \"$count\" > '{retry_counter}'\n"
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


def test_rate_limit_retry_after_header_overrides_default_backoff(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    retry_counter = tmp_path / "retry-count"
    retry_counter.write_text("0")

    make_executable(
        bin_dir / "pi",
        (
            "#!/usr/bin/env bash\n"
            f"count=$(cat '{retry_counter}')\n"
            "count=$((count + 1))\n"
            f"printf '%s' \"$count\" > '{retry_counter}'\n"
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
    assert "Retrying after transient error (class=rate_limit)" in result.stdout
    assert "wait=9s" in result.stdout


def test_permanent_api_error_is_written_for_parser(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_executable(
        bin_dir / "pi",
        "#!/usr/bin/env bash\necho '401 incorrect_api_key' >&2\nexit 1\n",
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
    parse_file = Path(parse_input_ref.read_text().strip())
    assert "API Error: API_KEY_INVALID" in parse_file.read_text()


def test_timeout_with_partial_output_exits_zero(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_executable(
        bin_dir / "pi",
        (
            "#!/usr/bin/env bash\n"
            "echo '## Investigation Notes'\n"
            "echo 'Collected partial evidence before timeout.'\n"
            "echo ''\n"
            "echo '## Verdict: WARN'\n"
            "sleep 2\n"
        ),
    )

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    env = make_env(bin_dir, diff_file)
    env["REVIEW_TIMEOUT"] = "1"
    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "parse-input: stdout (timeout, partial review)" in result.stdout


def test_fast_path_fallback_runs_on_timeout_with_no_output(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    call_counter = tmp_path / "call-count"
    call_counter.write_text("0")

    make_executable(
        bin_dir / "pi",
        (
            "#!/usr/bin/env bash\n"
            f"count=$(cat '{call_counter}')\n"
            "count=$((count + 1))\n"
            f"printf '%s' \"$count\" > '{call_counter}'\n"
            "if [[ \"$count\" -eq 1 ]]; then\n"
            "  sleep 5\n"  # primary attempt times out, no output
            "  exit 0\n"
            "fi\n"
            "cat <<'REVIEW'\n"
            "```json\n"
            '{"reviewer":"STUB","perspective":"security","verdict":"PASS",'
              '"confidence":0.8,"summary":"Fast-path review",'
              '"findings":[],"stats":{"files_reviewed":1,"files_with_issues":0,'
              '"critical":0,"major":0,"minor":0,"info":0}}\n'
            "```\n"
            "REVIEW\n"
        ),
    )

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    env = make_env(bin_dir, diff_file)
    env["REVIEW_TIMEOUT"] = "5"
    env["CERBERUS_TEST_FAST_PATH"] = "1"

    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        capture_output=True,
        text=True,
        timeout=40,
    )
    assert result.returncode == 0
    assert "fast-path fallback" in result.stdout.lower()
    assert "parse-input: fast-path output" in result.stdout


def test_short_timeout_skips_fast_path(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    make_executable(
        bin_dir / "pi",
        "#!/usr/bin/env bash\nsleep 2\n",
    )

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    env = make_env(bin_dir, diff_file)
    env["REVIEW_TIMEOUT"] = "1"

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


def test_primary_model_input_overrides_reviewer_model(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_stub_pi(bin_dir / "pi")

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


def test_fallback_model_used_after_primary_transient_failure(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    attempt_counter = tmp_path / "attempt-count"
    attempt_counter.write_text("0")

    make_executable(
        bin_dir / "pi",
        (
            "#!/usr/bin/env bash\n"
            f"count=$(cat '{attempt_counter}')\n"
            "count=$((count + 1))\n"
            f"printf '%s' \"$count\" > '{attempt_counter}'\n"
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

    diff_file = tmp_path / "diff.patch"
    write_simple_diff(diff_file)
    env = make_env(bin_dir, diff_file)
    env["CERBERUS_FALLBACK_MODELS"] = "openrouter/anthropic/claude-sonnet-4-5"

    result = subprocess.run(
        [str(RUN_REVIEWER), "security"],
        env=env,
        capture_output=True,
        text=True,
        timeout=40,
    )
    assert result.returncode == 0
    assert "Falling back to model:" in result.stdout
    model_used = Path("/tmp/security-model-used").read_text().strip()
    assert model_used == "openrouter/anthropic/claude-sonnet-4-5"


def test_auth_error_skips_fallback(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    attempt_counter = tmp_path / "attempt-count"
    attempt_counter.write_text("0")

    make_executable(
        bin_dir / "pi",
        (
            "#!/usr/bin/env bash\n"
            f"count=$(cat '{attempt_counter}')\n"
            "count=$((count + 1))\n"
            f"printf '%s' \"$count\" > '{attempt_counter}'\n"
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
    assert attempt_counter.read_text() == "1"
    assert "Falling back to model:" not in result.stdout


def test_empty_output_on_exit_zero_triggers_retry(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    retry_counter = tmp_path / "retry-count"
    retry_counter.write_text("0")

    make_executable(
        bin_dir / "pi",
        (
            "#!/usr/bin/env bash\n"
            f"count=$(cat '{retry_counter}')\n"
            "count=$((count + 1))\n"
            f"printf '%s' \"$count\" > '{retry_counter}'\n"
            "if [[ \"$count\" -eq 1 ]]; then\n"
            "  exit 0\n"
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
    assert "pi exited 0 but produced no output" in result.stdout
