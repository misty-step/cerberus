"""Tests for parse-review.py"""
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "parse-review.py"
FIXTURES = Path(__file__).parent / "fixtures"


def run_parse(input_text: str, env_extra: dict | None = None) -> tuple[int, str, str]:
    """Run parse-review.py with input text, return (exit_code, stdout, stderr)."""
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=input_text,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


def run_parse_file(path: Path, env_extra: dict | None = None) -> tuple[int, str, str]:
    """Run parse-review.py with a file argument."""
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


def run_parse_with_args(
    args: list[str],
    input_text: str = "",
    env_extra: dict | None = None,
) -> tuple[int, str, str]:
    """Run parse-review.py with explicit args."""
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        input=input_text,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


class TestParsePass:
    def test_extracts_valid_json(self):
        code, out, err = run_parse_file(FIXTURES / "sample-output-pass.txt")
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "PASS"
        assert data["reviewer"] == "APOLLO"

    def test_has_required_fields(self):
        code, out, _ = run_parse_file(FIXTURES / "sample-output-pass.txt")
        data = json.loads(out)
        for key in ["reviewer", "perspective", "verdict", "confidence", "summary", "findings", "stats"]:
            assert key in data

    def test_confidence_in_range(self):
        code, out, _ = run_parse_file(FIXTURES / "sample-output-pass.txt")
        data = json.loads(out)
        assert 0 <= data["confidence"] <= 1

    def test_stats_are_integers(self):
        code, out, _ = run_parse_file(FIXTURES / "sample-output-pass.txt")
        data = json.loads(out)
        for key in ["files_reviewed", "files_with_issues", "critical", "major", "minor", "info"]:
            assert isinstance(data["stats"][key], int)


class TestParseFail:
    def test_extracts_fail_verdict(self):
        code, out, _ = run_parse_file(FIXTURES / "sample-output-fail.txt")
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "FAIL"

    def test_findings_have_required_fields(self):
        code, out, _ = run_parse_file(FIXTURES / "sample-output-fail.txt")
        data = json.loads(out)
        for finding in data["findings"]:
            for key in ["severity", "category", "file", "line", "title", "description", "suggestion"]:
                assert key in finding


class TestParseErrors:
    def test_no_json_block(self):
        code, out, err = run_parse("Just some text with no json block")
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "FAIL"
        assert data["confidence"] == 0.0
        assert "no" in err.lower()

    def test_invalid_json(self):
        code, out, err = run_parse("```json\n{invalid json}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "FAIL"
        assert data["confidence"] == 0.0
        assert "invalid" in err.lower() or "json" in err.lower()

    def test_missing_required_field(self):
        incomplete = json.dumps({"reviewer": "TEST", "verdict": "PASS"})
        code, out, err = run_parse(f"```json\n{incomplete}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "FAIL"
        assert data["confidence"] == 0.0

    def test_invalid_verdict_value(self):
        bad = json.dumps({
            "reviewer": "TEST", "perspective": "test", "verdict": "MAYBE",
            "confidence": 0.5, "summary": "test", "findings": [],
            "stats": {"files_reviewed": 1, "files_with_issues": 0, "critical": 0, "major": 0, "minor": 0, "info": 0}
        })
        code, out, err = run_parse(f"```json\n{bad}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "FAIL"
        assert data["confidence"] == 0.0

    def test_confidence_out_of_range(self):
        bad = json.dumps({
            "reviewer": "TEST", "perspective": "test", "verdict": "PASS",
            "confidence": 1.5, "summary": "test", "findings": [],
            "stats": {"files_reviewed": 1, "files_with_issues": 0, "critical": 0, "major": 0, "minor": 0, "info": 0}
        })
        code, out, err = run_parse(f"```json\n{bad}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "FAIL"
        assert data["confidence"] == 0.0

    def test_uses_last_json_block(self):
        """When multiple json blocks exist, should use the last one."""
        first = json.dumps({"not": "valid"})
        second = json.dumps({
            "reviewer": "TEST", "perspective": "test", "verdict": "PASS",
            "confidence": 0.8, "summary": "Good", "findings": [],
            "stats": {"files_reviewed": 1, "files_with_issues": 0, "critical": 0, "major": 0, "minor": 0, "info": 0}
        })
        text = f"```json\n{first}\n```\nMore text\n```json\n{second}\n```"
        code, out, _ = run_parse(text)
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "PASS"


class TestParseArgs:
    def test_reviewer_flag_space(self, tmp_path):
        """--reviewer APOLLO sets reviewer name in fallback."""
        code, out, _ = run_parse_with_args(
            ["--reviewer", "APOLLO"],
            input_text="no json here",
        )
        assert code == 0
        data = json.loads(out)
        assert data["reviewer"] == "APOLLO"

    def test_reviewer_flag_equals(self, tmp_path):
        """--reviewer=APOLLO sets reviewer name in fallback."""
        code, out, _ = run_parse_with_args(
            ["--reviewer=APOLLO"],
            input_text="no json here",
        )
        assert code == 0
        data = json.loads(out)
        assert data["reviewer"] == "APOLLO"

    def test_reviewer_flag_missing_value(self):
        """--reviewer with no value produces fallback."""
        code, out, err = run_parse_with_args(["--reviewer"])
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "FAIL"
        assert "requires" in err.lower()

    def test_unknown_flag(self):
        """Unknown flags produce fallback."""
        code, out, err = run_parse_with_args(["--bogus"])
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "FAIL"
        assert "unknown" in err.lower()

    def test_too_many_positional_args(self, tmp_path):
        """Extra positional args produce fallback."""
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("x")
        f2.write_text("y")
        code, out, err = run_parse_with_args([str(f1), str(f2)])
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "FAIL"

    def test_file_not_found(self):
        """Nonexistent file produces fallback."""
        code, out, err = run_parse_with_args(["/nonexistent/path.txt"])
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "FAIL"
        assert "unable to read" in err.lower()

    def test_reviewer_with_file(self, tmp_path):
        """--reviewer works with file path argument."""
        f = tmp_path / "input.txt"
        f.write_text("no json here")
        code, out, _ = run_parse_with_args(
            ["--reviewer", "SENTINEL", str(f)],
        )
        assert code == 0
        data = json.loads(out)
        assert data["reviewer"] == "SENTINEL"


def test_verdict_consistency_override():
    """Verdict is recomputed from findings - LLM cannot self-report PASS with critical findings."""
    bad_pass = json.dumps(
        {
            "reviewer": "TEST",
            "perspective": "test",
            "verdict": "PASS",
            "confidence": 0.9,
            "summary": "Looks good",
            "findings": [
                {
                    "severity": "critical",
                    "category": "bug",
                    "file": "a.py",
                    "line": 1,
                    "title": "Critical bug",
                    "description": "desc",
                    "suggestion": "fix",
                }
            ],
            "stats": {
                "files_reviewed": 1,
                "files_with_issues": 1,
                "critical": 1,
                "major": 0,
                "minor": 0,
                "info": 0,
            },
        }
    )
    code, out, _ = run_parse(f"```json\n{bad_pass}\n```")
    assert code == 0
    data = json.loads(out)
    assert data["verdict"] == "FAIL"


def test_verdict_consistency_warn():
    """3+ minor findings forces WARN even if LLM says PASS."""
    bad_pass = json.dumps(
        {
            "reviewer": "TEST",
            "perspective": "test",
            "verdict": "PASS",
            "confidence": 0.9,
            "summary": "All good",
            "findings": [
                {
                    "severity": "minor",
                    "category": "style",
                    "file": "a.py",
                    "line": 1,
                    "title": f"Issue {i}",
                    "description": "desc",
                    "suggestion": "fix",
                }
                for i in range(3)
            ],
            "stats": {
                "files_reviewed": 1,
                "files_with_issues": 1,
                "critical": 0,
                "major": 0,
                "minor": 3,
                "info": 0,
            },
        }
    )
    code, out, _ = run_parse(f"```json\n{bad_pass}\n```")
    assert code == 0
    data = json.loads(out)
    assert data["verdict"] == "WARN"


def test_fallback_on_no_json_block():
    code, out, _ = run_parse(
        "Just some text with no json block",
        env_extra={"REVIEWER_NAME": "APOLLO"},
    )
    assert code == 0
    data = json.loads(out)
    assert data["verdict"] == "FAIL"
    assert data["confidence"] == 0.0
    assert data["reviewer"] == "APOLLO"


def test_fallback_on_invalid_json():
    code, out, _ = run_parse(
        "```json\n{invalid json}\n```",
        env_extra={"REVIEWER_NAME": "APOLLO"},
    )
    assert code == 0
    data = json.loads(out)
    assert data["verdict"] == "FAIL"
    assert data["confidence"] == 0.0
    assert data["reviewer"] == "APOLLO"


def test_fallback_default_reviewer():
    code, out, _ = run_parse("No JSON at all")
    assert code == 0
    data = json.loads(out)
    assert data["reviewer"] == "UNKNOWN"
