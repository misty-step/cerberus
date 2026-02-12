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
    env.pop("REVIEWER_NAME", None)
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
    env.pop("REVIEWER_NAME", None)
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
    env.pop("REVIEWER_NAME", None)
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
        assert data["verdict"] == "SKIP"  # Changed: missing JSON block is non-blocking
        assert data["confidence"] == 0.0
        assert "no" in err.lower() and "json" in err.lower()

    def test_fallback_uses_reviewer_name_and_perspective(self):
        """Fallback verdicts should use REVIEWER_NAME and PERSPECTIVE from env."""
        code, out, _ = run_parse(
            "No json here",
            env_extra={"REVIEWER_NAME": "APOLLO", "PERSPECTIVE": "correctness"},
        )
        assert code == 0
        data = json.loads(out)
        assert data["reviewer"] == "APOLLO"
        assert data["perspective"] == "correctness"

    def test_invalid_json(self):
        code, out, err = run_parse("```json\n{invalid json}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "FAIL"
        assert data["confidence"] == 0.0
        assert "invalid json" in err.lower() or "invalid" in err.lower()

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

    def test_timeout_recovery_with_json_block_is_not_skip(self, tmp_path):
        """Salvaged timeout output containing a JSON block should parse as normal review."""
        salvaged = tmp_path / "salvaged.txt"
        review = json.dumps(
            {
                "reviewer": "APOLLO",
                "perspective": "correctness",
                "verdict": "PASS",
                "confidence": 0.95,
                "summary": "Stub output",
                "findings": [],
                "stats": {
                    "files_reviewed": 1,
                    "files_with_issues": 0,
                    "critical": 0,
                    "major": 0,
                    "minor": 0,
                    "info": 0,
                },
            }
        )
        salvaged.write_text(f"```json\n{review}\n```\n")
        code, out, _ = run_parse_file(salvaged)
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "PASS"
        assert data["verdict"] != "SKIP"

    def test_timeout_marker_produces_skip(self, tmp_path):
        """Explicit timeout marker should produce SKIP verdict."""
        timeout_marker = tmp_path / "timeout.txt"
        timeout_marker.write_text("Review Timeout: timeout after 600s\n")
        code, out, _ = run_parse_file(
            timeout_marker,
            env_extra={"REVIEWER_NAME": "SENTINEL", "PERSPECTIVE": "security"},
        )
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert data["reviewer"] == "SENTINEL"
        assert data["perspective"] == "security"


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
        assert "--reviewer requires" in err.lower()

    def test_unknown_flag(self):
        """Unknown flags produce fallback."""
        code, out, err = run_parse_with_args(["--bogus"])
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "FAIL"
        assert "unknown argument" in err.lower()

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
        assert data["verdict"] == "SKIP"  # Changed: file read errors are non-blocking
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


def test_verdict_consistency_warn_on_five_minors():
    """5+ minor findings force WARN even if LLM says PASS."""
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
                    "category": f"style-{i}",
                    "file": "a.py",
                    "line": 1,
                    "title": f"Issue {i}",
                    "description": "desc",
                    "suggestion": "fix",
                }
                for i in range(5)
            ],
            "stats": {
                "files_reviewed": 1,
                "files_with_issues": 1,
                "critical": 0,
                "major": 0,
                "minor": 5,
                "info": 0,
            },
        }
    )
    code, out, _ = run_parse(f"```json\n{bad_pass}\n```")
    assert code == 0
    data = json.loads(out)
    assert data["verdict"] == "WARN"


def test_verdict_consistency_warn_on_three_minors_same_category():
    """3 minor findings in same category force WARN."""
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


def test_verdict_consistency_four_minors_without_category_cluster_is_pass():
    """4 minor findings across categories stay PASS."""
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
                    "category": f"cat-{i}",
                    "file": "a.py",
                    "line": 1,
                    "title": f"Issue {i}",
                    "description": "desc",
                    "suggestion": "fix",
                }
                for i in range(4)
            ],
            "stats": {
                "files_reviewed": 1,
                "files_with_issues": 1,
                "critical": 0,
                "major": 0,
                "minor": 4,
                "info": 0,
            },
        }
    )
    code, out, _ = run_parse(f"```json\n{bad_pass}\n```")
    assert code == 0
    data = json.loads(out)
    assert data["verdict"] == "PASS"


def test_verdict_consistency_two_majors_is_fail():
    """Exactly 2 major findings forces FAIL even if LLM says PASS."""
    bad_pass = json.dumps(
        {
            "reviewer": "TEST",
            "perspective": "test",
            "verdict": "PASS",
            "confidence": 0.9,
            "summary": "All good",
            "findings": [
                {
                    "severity": "major",
                    "category": "bug",
                    "file": "a.py",
                    "line": i,
                    "title": f"Major issue {i}",
                    "description": "desc",
                    "suggestion": "fix",
                }
                for i in range(2)
            ],
            "stats": {
                "files_reviewed": 1,
                "files_with_issues": 1,
                "critical": 0,
                "major": 2,
                "minor": 0,
                "info": 0,
            },
        }
    )
    code, out, _ = run_parse(f"```json\n{bad_pass}\n```")
    assert code == 0
    data = json.loads(out)
    assert data["verdict"] == "FAIL"


def test_verdict_consistency_one_major_is_warn():
    """Exactly 1 major finding forces WARN even if LLM says PASS."""
    bad_pass = json.dumps(
        {
            "reviewer": "TEST",
            "perspective": "test",
            "verdict": "PASS",
            "confidence": 0.9,
            "summary": "All good",
            "findings": [
                {
                    "severity": "major",
                    "category": "bug",
                    "file": "a.py",
                    "line": 1,
                    "title": "Major issue",
                    "description": "desc",
                    "suggestion": "fix",
                }
            ],
            "stats": {
                "files_reviewed": 1,
                "files_with_issues": 1,
                "critical": 0,
                "major": 1,
                "minor": 0,
                "info": 0,
            },
        }
    )
    code, out, _ = run_parse(f"```json\n{bad_pass}\n```")
    assert code == 0
    data = json.loads(out)
    assert data["verdict"] == "WARN"


def test_verdict_consistency_fail_with_no_findings_becomes_pass():
    """LLM claiming FAIL with no findings gets rewritten to PASS (DoS defense)."""
    dos_attempt = json.dumps(
        {
            "reviewer": "TEST",
            "perspective": "test",
            "verdict": "FAIL",
            "confidence": 0.9,
            "summary": "Everything is broken",
            "findings": [],
            "stats": {
                "files_reviewed": 1,
                "files_with_issues": 0,
                "critical": 0,
                "major": 0,
                "minor": 0,
                "info": 0,
            },
        }
    )
    code, out, _ = run_parse(f"```json\n{dos_attempt}\n```")
    assert code == 0
    data = json.loads(out)
    assert data["verdict"] == "PASS"


def test_verdict_consistency_low_confidence_findings_do_not_count():
    """Findings below confidence threshold do not affect verdict."""
    low_confidence_critical = json.dumps(
        {
            "reviewer": "TEST",
            "perspective": "test",
            "verdict": "FAIL",
            "confidence": 0.69,
            "summary": "Possible critical issue",
            "findings": [
                {
                    "severity": "critical",
                    "category": "injection",
                    "file": "a.py",
                    "line": 1,
                    "title": "Potential SQL injection",
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
    code, out, _ = run_parse(f"```json\n{low_confidence_critical}\n```")
    assert code == 0
    data = json.loads(out)
    assert data["verdict"] == "PASS"


def test_verdict_consistency_confidence_threshold_is_inclusive():
    """Confidence threshold includes 0.70 exactly."""
    threshold_critical = json.dumps(
        {
            "reviewer": "TEST",
            "perspective": "test",
            "verdict": "PASS",
            "confidence": 0.70,
            "summary": "Critical issue",
            "findings": [
                {
                    "severity": "critical",
                    "category": "injection",
                    "file": "a.py",
                    "line": 1,
                    "title": "SQL injection",
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
    code, out, _ = run_parse(f"```json\n{threshold_critical}\n```")
    assert code == 0
    data = json.loads(out)
    assert data["verdict"] == "FAIL"


class TestStaleKnowledgeDowngrade:
    def test_downgrades_version_does_not_exist(self):
        """Finding claiming a version 'does not exist' is downgraded to info."""
        review = json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness", "verdict": "FAIL",
            "confidence": 0.95, "summary": "Non-existent Go version",
            "findings": [{
                "severity": "critical",
                "category": "invalid-version",
                "file": "go.mod",
                "line": 3,
                "title": "Non-existent Go version breaks all builds",
                "description": "The go.mod file declares go 1.25 which does not exist as of January 2025.",
                "suggestion": "Use Go 1.23.x instead."
            }],
            "stats": {"files_reviewed": 1, "files_with_issues": 1,
                      "critical": 1, "major": 0, "minor": 0, "info": 0}
        })
        code, out, _ = run_parse(f"```json\n{review}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["findings"][0]["severity"] == "info"
        assert "[stale-knowledge]" in data["findings"][0]["title"]
        assert data["verdict"] == "PASS"

    def test_downgrades_not_yet_released(self):
        """Finding claiming something is 'not yet released' is downgraded."""
        review = json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness", "verdict": "FAIL",
            "confidence": 0.9, "summary": "Unreleased Python version",
            "findings": [{
                "severity": "critical",
                "category": "invalid-version",
                "file": "pyproject.toml",
                "line": 5,
                "title": "Python 3.14 is not yet released",
                "description": "requires-python >= 3.14 but Python 3.14 is not yet released.",
                "suggestion": "Use Python 3.12 or 3.13."
            }],
            "stats": {"files_reviewed": 1, "files_with_issues": 1,
                      "critical": 1, "major": 0, "minor": 0, "info": 0}
        })
        code, out, _ = run_parse(f"```json\n{review}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["findings"][0]["severity"] == "info"
        assert data["verdict"] == "PASS"

    def test_downgrades_latest_stable_is(self):
        """Finding asserting 'latest stable is X' is downgraded."""
        review = json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness", "verdict": "FAIL",
            "confidence": 0.95, "summary": "Invalid Node version",
            "findings": [{
                "severity": "critical",
                "category": "invalid-version",
                "file": ".node-version",
                "line": 1,
                "title": "Node 24 does not exist",
                "description": "The latest stable is Node 22.x. Node 24 has not been released.",
                "suggestion": "Use Node 22 LTS."
            }],
            "stats": {"files_reviewed": 1, "files_with_issues": 1,
                      "critical": 1, "major": 0, "minor": 0, "info": 0}
        })
        code, out, _ = run_parse(f"```json\n{review}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["findings"][0]["severity"] == "info"
        assert data["verdict"] == "PASS"

    def test_preserves_real_version_conflict_with_invalid_version_text(self):
        """'invalid version' + version-conflict category is NOT downgraded."""
        review = json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness", "verdict": "FAIL",
            "confidence": 0.9, "summary": "Version mismatch",
            "findings": [{
                "severity": "critical",
                "category": "version-conflict",
                "file": "package.json",
                "line": 10,
                "title": "Invalid version range in engines field",
                "description": "package.json declares an invalid version range that conflicts with .nvmrc 18.17.0.",
                "suggestion": "Align the versions."
            }],
            "stats": {"files_reviewed": 1, "files_with_issues": 1,
                      "critical": 1, "major": 0, "minor": 0, "info": 0}
        })
        code, out, _ = run_parse(f"```json\n{review}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["findings"][0]["severity"] == "critical"
        assert "[stale-knowledge]" not in data["findings"][0]["title"]
        assert data["verdict"] == "FAIL"

    def test_preserves_non_version_critical_findings(self):
        """Critical findings unrelated to versions are NOT downgraded."""
        review = json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness", "verdict": "FAIL",
            "confidence": 0.95, "summary": "SQL injection found",
            "findings": [{
                "severity": "critical",
                "category": "sql-injection",
                "file": "src/db.py",
                "line": 42,
                "title": "User input in SQL query",
                "description": "req.query.id is concatenated into the SQL string.",
                "suggestion": "Use parameterized queries."
            }],
            "stats": {"files_reviewed": 1, "files_with_issues": 1,
                      "critical": 1, "major": 0, "minor": 0, "info": 0}
        })
        code, out, _ = run_parse(f"```json\n{review}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["findings"][0]["severity"] == "critical"
        assert data["verdict"] == "FAIL"

    def test_downgrade_marker_is_set(self):
        """Downgraded findings have _stale_knowledge_downgraded flag."""
        review = json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness", "verdict": "FAIL",
            "confidence": 0.95, "summary": "Bad version",
            "findings": [{
                "severity": "critical",
                "category": "invalid-version",
                "file": "go.mod",
                "line": 3,
                "title": "Go 1.25 does not exist",
                "description": "go 1.25 does not exist. Latest stable is Go 1.23.",
                "suggestion": "Use Go 1.23."
            }],
            "stats": {"files_reviewed": 1, "files_with_issues": 1,
                      "critical": 1, "major": 0, "minor": 0, "info": 0}
        })
        code, out, _ = run_parse(f"```json\n{review}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["findings"][0].get("_stale_knowledge_downgraded") is True

    def test_stats_recomputed_after_downgrade(self):
        """Stats object is updated to reflect downgraded severities."""
        review = json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness", "verdict": "FAIL",
            "confidence": 0.95, "summary": "Bad version",
            "findings": [{
                "severity": "critical",
                "category": "invalid-version",
                "file": "go.mod",
                "line": 3,
                "title": "Go 1.25 does not exist",
                "description": "go 1.25 does not exist.",
                "suggestion": "Use Go 1.23."
            }],
            "stats": {"files_reviewed": 1, "files_with_issues": 1,
                      "critical": 1, "major": 0, "minor": 0, "info": 0}
        })
        code, out, _ = run_parse(f"```json\n{review}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["stats"]["critical"] == 0
        assert data["stats"]["info"] == 1

    def test_mixed_stale_and_real_findings(self):
        """Only stale finding is downgraded; real finding keeps verdict at FAIL."""
        review = json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness", "verdict": "FAIL",
            "confidence": 0.95, "summary": "Mixed findings",
            "findings": [
                {
                    "severity": "critical",
                    "category": "invalid-version",
                    "file": "go.mod",
                    "line": 3,
                    "title": "Go 1.25 does not exist",
                    "description": "go 1.25 does not exist.",
                    "suggestion": "Use Go 1.23."
                },
                {
                    "severity": "critical",
                    "category": "null-pointer",
                    "file": "main.go",
                    "line": 42,
                    "title": "Nil pointer dereference",
                    "description": "resp.Body accessed without nil check after error.",
                    "suggestion": "Check error first."
                },
            ],
            "stats": {"files_reviewed": 2, "files_with_issues": 2,
                      "critical": 2, "major": 0, "minor": 0, "info": 0}
        })
        code, out, _ = run_parse(f"```json\n{review}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["findings"][0]["severity"] == "info"
        assert data["findings"][1]["severity"] == "critical"
        assert data["stats"]["critical"] == 1
        assert data["stats"]["info"] == 1
        assert data["verdict"] == "FAIL"

    def test_short_context_term_requires_version_number(self):
        """'go' alone + 'does not exist' is NOT enough — needs a version number."""
        review = json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness", "verdict": "FAIL",
            "confidence": 0.9, "summary": "Missing binary",
            "findings": [{
                "severity": "critical",
                "category": "build-failure",
                "file": "Dockerfile",
                "line": 5,
                "title": "Go binary does not exist in PATH",
                "description": "The go binary does not exist in the container PATH. Build will fail.",
                "suggestion": "Add go to PATH."
            }],
            "stats": {"files_reviewed": 1, "files_with_issues": 1,
                      "critical": 1, "major": 0, "minor": 0, "info": 0}
        })
        code, out, _ = run_parse(f"```json\n{review}\n```")
        assert code == 0
        data = json.loads(out)
        # Must NOT be downgraded — this is a real build issue
        assert data["findings"][0]["severity"] == "critical"
        assert data["verdict"] == "FAIL"

    def test_release_claim_requires_version_number(self):
        """'latest version is' without a version number is NOT downgraded."""
        review = json.dumps({
            "reviewer": "SENTINEL", "perspective": "security", "verdict": "FAIL",
            "confidence": 0.9, "summary": "Vulnerable dependency",
            "findings": [{
                "severity": "critical",
                "category": "dependency-vulnerability",
                "file": "package.json",
                "line": 15,
                "title": "Known RCE in lodash",
                "description": "lodash has CVE-2020-8203. The latest version is patched.",
                "suggestion": "Upgrade lodash."
            }],
            "stats": {"files_reviewed": 1, "files_with_issues": 1,
                      "critical": 1, "major": 0, "minor": 0, "info": 0}
        })
        code, out, _ = run_parse(f"```json\n{review}\n```")
        assert code == 0
        data = json.loads(out)
        # Must NOT be downgraded — this is a real vulnerability
        assert data["findings"][0]["severity"] == "critical"
        assert data["verdict"] == "FAIL"

    def test_invalid_version_without_conflict_category_is_downgraded(self):
        """'invalid version' in text without version-conflict category IS downgraded."""
        review = json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness", "verdict": "FAIL",
            "confidence": 0.9, "summary": "Invalid version claimed",
            "findings": [{
                "severity": "major",
                "category": "invalid-version",
                "file": ".tool-versions",
                "line": 1,
                "title": "Invalid version specified",
                "description": "golang 1.25 is an invalid version number.",
                "suggestion": "Use golang 1.23."
            }],
            "stats": {"files_reviewed": 1, "files_with_issues": 1,
                      "critical": 0, "major": 1, "minor": 0, "info": 0}
        })
        code, out, _ = run_parse(f"```json\n{review}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["findings"][0]["severity"] == "info"
        assert data["findings"][0].get("_stale_knowledge_downgraded") is True

    def test_normalized_category_variants_all_protect(self):
        """All separator variants of version-conflict category protect findings."""
        for cat in ("version_conflict", "version mismatch", "dependency-conflict",
                    "dependency_mismatch", "dependency mismatch"):
            review = json.dumps({
                "reviewer": "APOLLO", "perspective": "correctness", "verdict": "FAIL",
                "confidence": 0.9, "summary": "Conflict",
                "findings": [{
                    "severity": "critical",
                    "category": cat,
                    "file": "go.mod",
                    "line": 1,
                    "title": "Invalid version range",
                    "description": "Declared an invalid version that conflicts.",
                    "suggestion": "Fix it."
                }],
                "stats": {"files_reviewed": 1, "files_with_issues": 1,
                          "critical": 1, "major": 0, "minor": 0, "info": 0}
            })
            code, out, _ = run_parse(f"```json\n{review}\n```")
            assert code == 0, f"Failed for category: {cat}"
            data = json.loads(out)
            assert data["findings"][0]["severity"] == "critical", \
                f"Finding wrongly downgraded for category: {cat}"


def test_fallback_on_no_json_block():
    code, out, _ = run_parse(
        "Just some text with no json block",
        env_extra={"REVIEWER_NAME": "APOLLO"},
    )
    assert code == 0
    data = json.loads(out)
    assert data["verdict"] == "SKIP"  # Changed: missing JSON block is non-blocking
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


def test_string_line_coerced_to_int():
    """String line numbers (e.g. "42") are coerced to int."""
    review = json.dumps({
        "reviewer": "TEST", "perspective": "test", "verdict": "PASS",
        "confidence": 0.8, "summary": "ok",
        "findings": [{
            "severity": "info", "category": "style", "file": "a.py",
            "line": "42", "title": "t", "description": "d", "suggestion": "s",
        }],
        "stats": {"files_reviewed": 1, "files_with_issues": 1,
                  "critical": 0, "major": 0, "minor": 0, "info": 1},
    })
    code, out, _ = run_parse(f"```json\n{review}\n```")
    assert code == 0
    data = json.loads(out)
    assert data["findings"][0]["line"] == 42
    assert isinstance(data["findings"][0]["line"], int)


def test_non_numeric_line_produces_fallback():
    """Non-numeric line value (e.g. "unknown") triggers fallback."""
    review = json.dumps({
        "reviewer": "TEST", "perspective": "test", "verdict": "PASS",
        "confidence": 0.8, "summary": "ok",
        "findings": [{
            "severity": "info", "category": "style", "file": "a.py",
            "line": "not-a-number", "title": "t", "description": "d", "suggestion": "s",
        }],
        "stats": {"files_reviewed": 1, "files_with_issues": 1,
                  "critical": 0, "major": 0, "minor": 0, "info": 1},
    })
    code, out, _ = run_parse(f"```json\n{review}\n```")
    assert code == 0
    data = json.loads(out)
    assert data["verdict"] == "FAIL"
    assert data["confidence"] == 0.0


def test_invalid_finding_severity():
    """Invalid severity on a finding triggers fallback."""
    review = json.dumps({
        "reviewer": "TEST", "perspective": "test", "verdict": "PASS",
        "confidence": 0.8, "summary": "ok",
        "findings": [{
            "severity": "extreme", "category": "style", "file": "a.py",
            "line": 1, "title": "t", "description": "d", "suggestion": "s",
        }],
        "stats": {"files_reviewed": 1, "files_with_issues": 1,
                  "critical": 0, "major": 0, "minor": 0, "info": 1},
    })
    code, out, _ = run_parse(f"```json\n{review}\n```")
    assert code == 0
    data = json.loads(out)
    assert data["verdict"] == "FAIL"
    assert data["confidence"] == 0.0


def test_root_not_object():
    """JSON array at root triggers fallback (note: regex only matches {}, so array is 'no block')."""
    code, out, _ = run_parse('```json\n[1, 2, 3]\n```')
    assert code == 0
    data = json.loads(out)
    assert data["verdict"] == "SKIP"  # Changed: extract_json_block regex only matches objects, not arrays
    assert data["confidence"] == 0.0


class TestScratchpadInput:
    """Tests for scratchpad review document handling."""

    def test_extracts_json_from_scratchpad(self):
        """parse-review.py works with scratchpad format (markdown + JSON block)."""
        code, out, _ = run_parse_file(FIXTURES / "sample-scratchpad-complete.md")
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "PASS"
        assert data["reviewer"] == "ATHENA"
        assert data["confidence"] == 0.88

    def test_scratchpad_findings_preserved(self):
        """Findings from scratchpad JSON are preserved."""
        code, out, _ = run_parse_file(FIXTURES / "sample-scratchpad-complete.md")
        data = json.loads(out)
        assert len(data["findings"]) == 1
        assert data["findings"][0]["severity"] == "info"

    def test_partial_scratchpad_extracts_verdict_from_header(self):
        """Scratchpad without JSON block but with ## Verdict: PASS header extracts PASS."""
        code, out, _ = run_parse_file(
            FIXTURES / "sample-scratchpad-partial.md",
            env_extra={"REVIEWER_NAME": "APOLLO"},
        )
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "PASS"
        assert data["reviewer"] == "APOLLO"
        assert data["confidence"] < 0.5  # low confidence for partial

    def test_partial_scratchpad_defaults_to_warn(self):
        """Scratchpad without JSON block or verdict header defaults to WARN."""
        # Write a scratchpad with investigation notes but no verdict header
        partial_text = "# Review\n\n## Investigation Notes\n- Checked files\n- Found nothing yet\n"
        code, out, _ = run_parse(partial_text, env_extra={"REVIEWER_NAME": "TEST"})
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "WARN"

    def test_partial_scratchpad_includes_notes_in_summary(self):
        """Partial scratchpad includes investigation notes in the summary."""
        code, out, _ = run_parse_file(
            FIXTURES / "sample-scratchpad-partial.md",
            env_extra={"REVIEWER_NAME": "APOLLO"},
        )
        data = json.loads(out)
        assert "investigation" in data["summary"].lower() or "partial" in data["summary"].lower() or "timed out" in data["summary"].lower()


class TestApiErrors:
    def test_detects_api_key_invalid_error(self):
        error_text = """API Error: API_KEY_INVALID

The OpenRouter API returned an error that prevents the review from completing:

401 Unauthorized: incorrect_api_key

Please check your API key and quota settings.
"""
        code, out, err = run_parse(error_text, env_extra={"REVIEWER_NAME": "SENTINEL", "PERSPECTIVE": "security"})
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert data["reviewer"] == "SENTINEL"
        assert data["perspective"] == "security"
        assert "API_KEY_INVALID" in data["summary"]
        assert data["confidence"] == 0.0

    def test_detects_quota_exceeded_error(self):
        """Legacy API_QUOTA_EXCEEDED marker is unified to API_CREDITS_DEPLETED."""
        error_text = """API Error: API_QUOTA_EXCEEDED

The OpenRouter API returned an error:

exceeded_current_quota

Please check your API key and quota settings.
"""
        code, out, err = run_parse(error_text)
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert "credits depleted" in data["summary"].lower()

    def test_detects_generic_api_error(self):
        error_text = """API Error: API_ERROR

The OpenRouter API returned an error that prevents the review from completing.
"""
        code, out, err = run_parse(error_text)
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"

    def test_skip_verdict_has_required_fields(self):
        error_text = """API Error: API_KEY_INVALID

Error message here.
"""
        code, out, _ = run_parse(error_text)
        assert code == 0
        data = json.loads(out)
        for key in ["reviewer", "perspective", "verdict", "confidence", "summary", "findings", "stats"]:
            assert key in data

    def test_skip_verdict_has_finding_with_api_error(self):
        error_text = """API Error: API_KEY_INVALID

Error message here.
"""
        code, out, _ = run_parse(error_text)
        assert code == 0
        data = json.loads(out)
        assert len(data["findings"]) == 1
        finding = data["findings"][0]
        assert finding["category"] == "api_error"
        assert finding["severity"] == "info"

    def test_detects_401_in_output_without_explicit_marker(self):
        """Should detect API errors even without explicit 'API Error:' marker."""
        error_text = """
Something went wrong with the API call.

401 Unauthorized: invalid API key provided

Please try again later.
"""
        code, out, err = run_parse(error_text)
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"

    def test_detects_rate_limit_without_explicit_marker(self):
        """Should detect rate limit errors even without explicit 'API Error:' marker."""
        error_text = """
The API returned an error:
429 rate limit exceeded

Please retry after some time.
"""
        code, out, err = run_parse(error_text)
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert "RATE_LIMIT" in data["summary"]

    def test_detects_timeout_marker(self):
        timeout_text = """Review Timeout: timeout after 120s

APOLLO (correctness) exceeded the configured timeout.
"""
        code, out, err = run_parse(timeout_text, env_extra={"REVIEWER_NAME": "APOLLO"})
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert data["reviewer"] == "APOLLO"
        assert "timeout after 120s" in data["summary"]
        assert data["findings"][0]["category"] == "timeout"

    def test_skip_stats_are_zero(self):
        error_text = """API Error: API_ERROR

Some error.
"""
        code, out, _ = run_parse(error_text)
        assert code == 0
        data = json.loads(out)
        stats = data["stats"]
        assert stats["files_reviewed"] == 0
        assert stats["files_with_issues"] == 0
        assert stats["critical"] == 0
        assert stats["major"] == 0
        assert stats["minor"] == 0
        assert stats["info"] == 1


class TestCreditExhaustion:
    """Tests for 402 Payment Required and credit exhaustion detection."""

    def test_detects_402_with_explicit_marker(self):
        error_text = """API Error: API_CREDITS_DEPLETED

The OpenRouter API returned an error:

402 Payment Required

Please check your API key and quota settings.
"""
        code, out, _ = run_parse(error_text)
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert "API_CREDITS_DEPLETED" in data["summary"]
        assert "credits depleted" in data["summary"].lower()

    def test_detects_402_without_explicit_marker(self):
        """402 in raw output (no 'API Error:' prefix) should still produce SKIP."""
        error_text = """
The API returned an error:
402 Payment Required

Your account has insufficient credits.
"""
        code, out, _ = run_parse(error_text)
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert "CREDITS_DEPLETED" in data["summary"]

    def test_detects_payment_required_text(self):
        """'payment required' phrase triggers credit depletion detection."""
        error_text = """
Error: payment required - please add credits to your account.
"""
        code, out, _ = run_parse(error_text)
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert "CREDITS_DEPLETED" in data["summary"]

    def test_detects_insufficient_quota(self):
        """'insufficient_quota' error code triggers credit depletion."""
        error_text = """
API call failed: insufficient_quota
"""
        code, out, _ = run_parse(error_text)
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert "CREDITS_DEPLETED" in data["summary"]

    def test_credit_error_suggestion_mentions_fallback(self):
        """Credit exhaustion suggestion should mention fallback provider."""
        error_text = """API Error: API_CREDITS_DEPLETED

402 Payment Required
"""
        code, out, _ = run_parse(error_text)
        assert code == 0
        data = json.loads(out)
        finding = data["findings"][0]
        assert "fallback" in finding["suggestion"].lower()

    def test_quota_exceeded_also_gets_credit_message(self):
        """API_QUOTA_EXCEEDED should also get the 'credits depleted' summary."""
        error_text = """API Error: API_QUOTA_EXCEEDED

exceeded_current_quota
"""
        code, out, _ = run_parse(error_text)
        assert code == 0
        data = json.loads(out)
        assert "credits depleted" in data["summary"].lower()

    def test_credits_depleted_takes_priority_over_quota(self):
        """When both credit and quota signals present, CREDITS_DEPLETED wins."""
        error_text = """API Error: API_CREDITS_DEPLETED

Your quota has been exceeded. billing issue detected.
"""
        code, out, _ = run_parse(error_text)
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert "API_CREDITS_DEPLETED" in data["summary"]

    def test_exceeded_current_quota_without_marker(self):
        """exceeded_current_quota without API Error prefix maps to CREDITS_DEPLETED."""
        error_text = "\nError from API: exceeded_current_quota\n"
        code, out, _ = run_parse(error_text)
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert "CREDITS_DEPLETED" in data["summary"]

    def test_billing_error_without_marker(self):
        """billing error without API Error prefix maps to CREDITS_DEPLETED."""
        error_text = "\nError: billing issue with your account.\n"
        code, out, _ = run_parse(error_text)
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert "CREDITS_DEPLETED" in data["summary"]

    def test_non_credit_error_keeps_generic_suggestion(self):
        """API_KEY_INVALID should get generic suggestion, not credit-specific."""
        error_text = "API Error: API_KEY_INVALID\n401 Unauthorized\n"
        code, out, _ = run_parse(error_text)
        assert code == 0
        data = json.loads(out)
        finding = data["findings"][0]
        assert "Check API key" in finding["suggestion"]
        assert "fallback" not in finding["suggestion"].lower()


class TestEnrichedTimeoutVerdicts:
    """Tests for enriched timeout markers with file list and diagnostics."""

    def test_enriched_timeout_includes_file_list(self):
        """Enriched timeout marker includes files_in_diff in the verdict."""
        timeout_text = """Review Timeout: timeout after 600s
SENTINEL (security) exceeded the configured timeout.
Fast-path: yes
Files in diff: src/main.py
src/utils.py
tests/test_app.py
Next steps: Increase timeout, reduce diff size, or check model provider status.
"""
        code, out, _ = run_parse(timeout_text, env_extra={"REVIEWER_NAME": "SENTINEL"})
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert data["reviewer"] == "SENTINEL"
        assert "timeout after 600s" in data["summary"]
        assert "src/main.py" in data["findings"][0]["description"]
        assert "files_in_diff" in data
        # Must capture ALL files, not just the first line.
        assert "src/main.py" in data["files_in_diff"]
        assert "src/utils.py" in data["files_in_diff"]
        assert "tests/test_app.py" in data["files_in_diff"]

    def test_enriched_timeout_fast_path_yes_suggests_provider_stall(self):
        """When fast-path was attempted, suggestion mentions provider stall."""
        timeout_text = """Review Timeout: timeout after 600s
APOLLO (correctness) exceeded the configured timeout.
Fast-path: yes
Files in diff: app.py
Next steps: Increase timeout, reduce diff size, or check model provider status.
"""
        code, out, _ = run_parse(timeout_text, env_extra={"REVIEWER_NAME": "APOLLO"})
        assert code == 0
        data = json.loads(out)
        assert "provider" in data["findings"][0]["suggestion"].lower()

    def test_enriched_timeout_fast_path_no_omits_stall_hint(self):
        """When fast-path was not attempted, no provider stall hint."""
        timeout_text = """Review Timeout: timeout after 60s
APOLLO (correctness) exceeded the configured timeout.
Fast-path: no
Files in diff: app.py
Next steps: Increase timeout (current: 60s is too short for fast-path fallback).
"""
        code, out, _ = run_parse(timeout_text, env_extra={"REVIEWER_NAME": "APOLLO"})
        assert code == 0
        data = json.loads(out)
        # Should still be a valid SKIP verdict
        assert data["verdict"] == "SKIP"
        # Provider stall hint should NOT be in suggestion when fast-path wasn't tried
        assert "stalled" not in data["findings"][0]["suggestion"].lower()

    def test_basic_timeout_marker_still_works(self):
        """Old-style timeout marker (no enrichment) still parses correctly."""
        timeout_text = """Review Timeout: timeout after 600s
APOLLO (correctness) exceeded the configured timeout.
"""
        code, out, _ = run_parse(timeout_text, env_extra={"REVIEWER_NAME": "APOLLO"})
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert data["reviewer"] == "APOLLO"
        assert "files_in_diff" not in data  # No enrichment present

    def test_enriched_timeout_next_steps_in_description(self):
        """Enriched timeout includes concrete next steps."""
        timeout_text = """Review Timeout: timeout after 600s
VULCAN (performance) exceeded the configured timeout.
Fast-path: yes
Files in diff: big_module.py
Next steps: Increase timeout, reduce diff size, or check model provider status.
"""
        code, out, _ = run_parse(timeout_text, env_extra={"REVIEWER_NAME": "VULCAN"})
        assert code == 0
        data = json.loads(out)
        finding = data["findings"][0]
        assert "big_module.py" in finding["description"]
        assert "timeout" in finding["suggestion"].lower() or "model" in finding["suggestion"].lower()
