"""End-to-end local pipeline tests with mocked reviewer runtime."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
RUN_REVIEWER = REPO_ROOT / "scripts" / "run-reviewer.sh"
PARSE_REVIEW = REPO_ROOT / "scripts" / "parse-review.py"
AGGREGATE_VERDICT = REPO_ROOT / "scripts" / "aggregate-verdict.py"


def make_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def build_env(bin_dir: Path, diff_file: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["CERBERUS_ROOT"] = str(REPO_ROOT)
    env["CERBERUS_TMP"] = "/tmp"
    env["GH_DIFF_FILE"] = str(diff_file)
    env["OPENROUTER_API_KEY"] = "test-key-not-real"
    env["OPENCODE_MAX_STEPS"] = "5"
    env["REVIEW_TIMEOUT"] = "5"
    return env


def test_all_reviewers_fail_end_to_end(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    make_executable(
        bin_dir / "opencode",
        (
            "#!/usr/bin/env bash\n"
            "cat <<'REVIEW'\n"
            "```json\n"
            '{"reviewer":"STUB","perspective":"security","verdict":"FAIL",'
              '"confidence":0.95,"summary":"Blocking issue",'
              '"findings":[{"severity":"major","category":"bug","file":"x.py","line":1,'
              '"title":"major-1","description":"d","suggestion":"s"},'
              '{"severity":"major","category":"bug","file":"x.py","line":2,'
              '"title":"major-2","description":"d","suggestion":"s"}],'
              '"stats":{"files_reviewed":1,"files_with_issues":1,'
              '"critical":0,"major":2,"minor":0,"info":0}}\n'
            "```\n"
            "REVIEW\n"
        ),
    )

    diff_file = tmp_path / "pr.diff"
    diff_file.write_text("diff --git a/core.py b/core.py\n+print('change')\n")
    env = build_env(bin_dir, diff_file)

    verdict_dir = tmp_path / "verdicts"
    verdict_dir.mkdir()
    perspectives = ("correctness", "architecture", "security")

    for perspective in perspectives:
        run_result = subprocess.run(
            [str(RUN_REVIEWER), perspective],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert run_result.returncode == 0, run_result.stderr

        parse_input_path = Path(f"/tmp/{perspective}-parse-input")
        assert parse_input_path.exists()
        parse_input = parse_input_path.read_text().strip()

        parse_result = subprocess.run(
            [
                sys.executable,
                str(PARSE_REVIEW),
                "--reviewer",
                perspective.upper(),
                parse_input,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert parse_result.returncode == 0, parse_result.stderr

        (verdict_dir / f"{perspective}.json").write_text(parse_result.stdout)

    aggregate_result = subprocess.run(
        [sys.executable, str(AGGREGATE_VERDICT), str(verdict_dir)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert aggregate_result.returncode == 0, aggregate_result.stderr

    council = json.loads(Path("/tmp/council-verdict.json").read_text())
    assert council["verdict"] == "FAIL"
    assert council["stats"]["fail"] == len(perspectives)
