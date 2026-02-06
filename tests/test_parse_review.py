"""Tests for parse-review.py"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "parse-review.py"
FIXTURES = Path(__file__).parent / "fixtures"


def run_parse(input_text: str) -> tuple[int, str, str]:
    """Run parse-review.py with input text, return (exit_code, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=input_text,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


def run_parse_file(path: Path) -> tuple[int, str, str]:
    """Run parse-review.py with a file argument."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        capture_output=True,
        text=True,
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
        code, _, err = run_parse("Just some text with no json block")
        assert code == 2
        assert "no" in err.lower()

    def test_invalid_json(self):
        code, _, err = run_parse("```json\n{invalid json}\n```")
        assert code == 2
        assert "invalid" in err.lower() or "json" in err.lower()

    def test_missing_required_field(self):
        incomplete = json.dumps({"reviewer": "TEST", "verdict": "PASS"})
        code, _, err = run_parse(f"```json\n{incomplete}\n```")
        assert code == 2

    def test_invalid_verdict_value(self):
        bad = json.dumps({
            "reviewer": "TEST", "perspective": "test", "verdict": "MAYBE",
            "confidence": 0.5, "summary": "test", "findings": [],
            "stats": {"files_reviewed": 1, "files_with_issues": 0, "critical": 0, "major": 0, "minor": 0, "info": 0}
        })
        code, _, err = run_parse(f"```json\n{bad}\n```")
        assert code == 2

    def test_confidence_out_of_range(self):
        bad = json.dumps({
            "reviewer": "TEST", "perspective": "test", "verdict": "PASS",
            "confidence": 1.5, "summary": "test", "findings": [],
            "stats": {"files_reviewed": 1, "files_with_issues": 0, "critical": 0, "major": 0, "minor": 0, "info": 0}
        })
        code, _, err = run_parse(f"```json\n{bad}\n```")
        assert code == 2

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
