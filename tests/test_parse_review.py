"""Tests for parse-review.py"""
import json
import os
import subprocess
import sys
import uuid
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


def run_parse_in_cwd(
    input_text: str,
    cwd: Path,
    env_extra: dict | None = None,
) -> tuple[int, str, str]:
    """Run parse-review.py with input text in a specific working directory."""
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
        cwd=str(cwd),
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
        assert data["verdict"] == "SKIP"  # Parse failures are non-blocking
        assert data["confidence"] == 0.0
        assert "invalid json" in err.lower() or "invalid" in err.lower()

    def test_missing_required_field(self):
        incomplete = json.dumps({"reviewer": "TEST", "verdict": "PASS"})
        code, out, err = run_parse(f"```json\n{incomplete}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"  # Parse failures are non-blocking
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
        assert data["verdict"] == "SKIP"  # Parse failures are non-blocking
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
        assert data["verdict"] == "SKIP"  # Parse failures are non-blocking
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


class TestParseFailureMetadata:
    def test_parse_failure_metadata_is_preserved_in_summary(self, tmp_path):
        """Recovery metadata is surfaced when parse retries were attempted."""
        # Unique perspective avoids collisions if the suite is ever parallelized.
        perspective = f"PARSE_META_{uuid.uuid4().hex}"
        models_file = tmp_path / f"{perspective}-parse-failure-models.txt"
        retries_file = tmp_path / f"{perspective}-parse-failure-retries.txt"

        models_file.write_text("gpt-4o-mini\ngpt-4.1\n")
        retries_file.write_text("2")

        code, out, _ = run_parse(
            "Reviewer output was not structured.",
            env_extra={
                "PERSPECTIVE": perspective,
                "REVIEWER_NAME": "VULCAN",
                "CERBERUS_TMP": str(tmp_path),
            },
        )

        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert data["confidence"] == 0.0
        assert "2 parse-recovery retries attempted" in data["summary"]
        assert "Models tried: gpt-4o-mini, gpt-4.1" in data["summary"]
        assert len(data["findings"]) == 1
        finding = data["findings"][0]
        assert finding["category"] == "parse-failure"
        assert finding["severity"] == "info"
        assert "structured JSON block after retries" in finding["description"]


class TestParseRecoveryAndMalformedInput:
    def test_partial_json_fence_is_skip(self):
        """Partial JSON (starts a ```json fence but never closes) is non-blocking SKIP."""
        code, out, err = run_parse("```json\n{\"verdict\": \"PASS\",")
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert data["confidence"] == 0.0
        assert data["summary"].startswith("Review output could not be parsed:")
        assert len(data["findings"]) == 0
        assert "no ```json block found" in err.lower()


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
        assert data["verdict"] == "SKIP"  # Parse failures are non-blocking
        assert "--reviewer requires" in err.lower()

    def test_unknown_flag(self):
        """Unknown flags produce fallback."""
        code, out, err = run_parse_with_args(["--bogus"])
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"  # Parse failures are non-blocking
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
        assert data["verdict"] == "SKIP"  # Parse failures are non-blocking

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


class TestEvidenceDowngrade:
    @staticmethod
    def _write_diff(cwd: Path, changed_files: list[str]) -> Path:
        diff_path = cwd / "pr.diff"
        blocks = []
        for file in changed_files:
            blocks.append(
                "\n".join(
                    [
                        f"diff --git a/{file} b/{file}",
                        "index 0000000..1111111 100644",
                        f"--- a/{file}",
                        f"+++ b/{file}",
                        "@@ -0,0 +1,1 @@",
                        "+stub",
                        "",
                    ]
                )
            )
        diff_path.write_text("\n".join(blocks))
        return diff_path

    @staticmethod
    def _wrap_json(obj: dict) -> str:
        return f"```json\n{json.dumps(obj)}\n```"

    @staticmethod
    def _review(finding: dict, verdict: str = "PASS", summary: str = "Major issue") -> dict:
        severity = finding.get("severity")
        stats = {
            "files_reviewed": 1,
            "files_with_issues": 1,
            "critical": 1 if severity == "critical" else 0,
            "major": 1 if severity == "major" else 0,
            "minor": 1 if severity == "minor" else 0,
            "info": 1 if severity == "info" else 0,
        }
        return {
            "reviewer": "APOLLO",
            "perspective": "correctness",
            "verdict": verdict,
            "confidence": 0.95,
            "summary": summary,
            "findings": [finding],
            "stats": stats,
        }

    def test_missing_evidence_annotated_not_demoted(self, tmp_path):
        """Findings without evidence are annotated [unverified] but keep their severity."""
        (tmp_path / "app.py").write_text("x = 1\n")
        diff = self._write_diff(tmp_path, ["app.py"])

        review = self._review(
            {
                "severity": "major",
                "category": "bug",
                "file": "app.py",
                "line": 1,
                "title": "Wrong thing",
                "description": "desc",
                "suggestion": "fix",
            },
            verdict="FAIL",
        )

        code, out, _ = run_parse_in_cwd(
            self._wrap_json(review),
            cwd=tmp_path,
            env_extra={"GH_DIFF_FILE": str(diff)},
        )
        assert code == 0
        data = json.loads(out)
        # Severity is NOT lowered — the finding still counts toward thresholds
        assert data["findings"][0]["severity"] == "major"
        assert data["findings"][0]["title"].startswith("[unverified] ")
        assert data["findings"][0]["_evidence_unverified"] is True
        assert data["findings"][0]["_evidence_reason"] == "missing-evidence"
        assert "could not be verified" in data["findings"][0]["description"]
        assert "[unverified: 1]" in data["summary"]
        # 1 major → WARN (enforce_verdict_consistency)
        assert data["verdict"] == "WARN"
        assert data["stats"]["major"] == 1

    def test_evidence_mismatch_annotated_not_demoted(self, tmp_path):
        """Findings with mismatched evidence are annotated but keep their severity."""
        (tmp_path / "app.py").write_text("x = 1\n")
        diff = self._write_diff(tmp_path, ["app.py"])

        review = self._review(
            {
                "severity": "major",
                "category": "bug",
                "file": "app.py",
                "line": 1,
                "title": "Wrong thing",
                "description": "desc",
                "evidence": "x = 2",
                "suggestion": "fix",
            },
            verdict="WARN",
        )

        code, out, _ = run_parse_in_cwd(
            self._wrap_json(review),
            cwd=tmp_path,
            env_extra={"GH_DIFF_FILE": str(diff)},
        )
        assert code == 0
        data = json.loads(out)
        assert data["findings"][0]["severity"] == "major"
        assert data["findings"][0]["title"].startswith("[unverified] ")
        assert data["findings"][0]["_evidence_reason"] == "evidence-mismatch"
        # 1 major → WARN
        assert data["verdict"] == "WARN"

    def test_evidence_match_keeps_severity(self, tmp_path):
        (tmp_path / "app.py").write_text("x = 1\n")
        diff = self._write_diff(tmp_path, ["app.py"])

        review = self._review(
            {
                "severity": "major",
                "category": "bug",
                "file": "app.py",
                "line": 1,
                "title": "Real issue",
                "description": "desc",
                "evidence": "x = 1",
                "suggestion": "fix",
            }
        )

        code, out, _ = run_parse_in_cwd(
            self._wrap_json(review),
            cwd=tmp_path,
            env_extra={"GH_DIFF_FILE": str(diff)},
        )
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "WARN"
        assert data["findings"][0]["severity"] == "major"
        assert data["findings"][0]["_evidence_verified"] is True

    def test_out_of_scope_file_annotated_not_demoted(self, tmp_path):
        """Out-of-scope findings are annotated [out-of-scope] but keep their severity."""
        (tmp_path / "app.py").write_text("x = 1\n")
        (tmp_path / "other.py").write_text("y = 2\n")
        diff = self._write_diff(tmp_path, ["app.py"])

        review = self._review(
            {
                "severity": "major",
                "category": "bug",
                "file": "other.py",
                "line": 1,
                "title": "Out of scope",
                "description": "desc",
                "evidence": "y = 2",
                "suggestion": "fix",
            },
            verdict="FAIL",
        )

        code, out, _ = run_parse_in_cwd(
            self._wrap_json(review),
            cwd=tmp_path,
            env_extra={"GH_DIFF_FILE": str(diff)},
        )
        assert code == 0
        data = json.loads(out)
        assert data["findings"][0]["severity"] == "major"
        assert data["findings"][0]["title"].startswith("[out-of-scope] ")
        assert data["findings"][0]["_evidence_reason"] == "out-of-scope"
        # Severity is preserved → finding still counts toward verdict
        assert data["verdict"] == "WARN"

    def test_defaults_change_scope_allows_out_of_diff(self, tmp_path):
        (tmp_path / "app.py").write_text("x = 1\n")
        (tmp_path / "other.py").write_text("y = 2\n")
        diff = self._write_diff(tmp_path, ["app.py"])

        review = self._review(
            {
                "severity": "major",
                "category": "defaults-change",
                "scope": "defaults-change",
                "file": "other.py",
                "line": 1,
                "title": "New default path is unsafe",
                "description": "desc",
                "evidence": "y = 2",
                "suggestion": "fix",
            }
        )

        code, out, _ = run_parse_in_cwd(
            self._wrap_json(review),
            cwd=tmp_path,
            env_extra={"GH_DIFF_FILE": str(diff)},
        )
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "WARN"
        assert data["findings"][0]["severity"] == "major"
        assert data["findings"][0]["_evidence_verified"] is True

    def test_empty_evidence_after_normalization_annotated_not_demoted(self, tmp_path):
        """Findings with empty evidence after normalization are annotated but keep severity."""
        (tmp_path / "app.py").write_text("x = 1\n")
        diff = self._write_diff(tmp_path, ["app.py"])

        review = self._review(
            {
                "severity": "major",
                "category": "bug",
                "file": "app.py",
                "line": 1,
                "title": "Empty evidence",
                "description": "desc",
                "evidence": "```text\n+\n```",
                "suggestion": "fix",
            }
        )

        code, out, _ = run_parse_in_cwd(
            self._wrap_json(review),
            cwd=tmp_path,
            env_extra={"GH_DIFF_FILE": str(diff)},
        )
        assert code == 0
        data = json.loads(out)
        assert data["findings"][0]["severity"] == "major"
        assert data["findings"][0]["_evidence_reason"] == "empty-evidence"
        assert data["verdict"] == "WARN"

    def test_file_not_found_annotated_not_demoted(self, tmp_path):
        """Findings referencing non-existent files are annotated but keep their severity."""
        diff = self._write_diff(tmp_path, ["missing.py"])

        review = self._review(
            {
                "severity": "major",
                "category": "bug",
                "file": "missing.py",
                "line": 1,
                "title": "Missing file",
                "description": "desc",
                "evidence": "x = 1",
                "suggestion": "fix",
            },
            verdict="FAIL",
        )

        code, out, _ = run_parse_in_cwd(
            self._wrap_json(review),
            cwd=tmp_path,
            env_extra={"GH_DIFF_FILE": str(diff)},
        )
        assert code == 0
        data = json.loads(out)
        assert data["findings"][0]["severity"] == "major"
        assert data["findings"][0]["_evidence_reason"] == "file-not-found"
        assert data["verdict"] == "WARN"

    def test_truncation_does_not_break_verification(self, tmp_path):
        long_val = "a" * 2100
        long_line = f'x = "{long_val}"'
        (tmp_path / "app.py").write_text(long_line + "\n")
        diff = self._write_diff(tmp_path, ["app.py"])

        review = self._review(
            {
                "severity": "major",
                "category": "bug",
                "file": "app.py",
                "line": 1,
                "title": "Long evidence",
                "description": "desc",
                "evidence": long_line,
                "suggestion": "fix",
            }
        )

        code, out, _ = run_parse_in_cwd(
            self._wrap_json(review),
            cwd=tmp_path,
            env_extra={"GH_DIFF_FILE": str(diff)},
        )
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "WARN"
        assert data["findings"][0]["severity"] == "major"
        assert data["findings"][0]["_evidence_verified"] is True
        assert data["findings"][0]["evidence"].endswith("...")

    def test_diff_parser_handles_quoted_paths_with_spaces(self, tmp_path):
        file_name = "hello world.txt"
        (tmp_path / file_name).write_text("x = 1\n")

        diff = tmp_path / "pr.diff"
        diff.write_text(
            "\n".join(
                [
                    f'diff --git "a/{file_name}" "b/{file_name}"',
                    "index 0000000..1111111 100644",
                    f'--- "a/{file_name}"',
                    f'+++ "b/{file_name}"',
                    "@@ -0,0 +1,1 @@",
                    "+stub",
                    "",
                ]
            )
        )

        review = self._review(
            {
                "severity": "major",
                "category": "bug",
                "file": file_name,
                "line": 1,
                "title": "Space path in-scope",
                "description": "desc",
                "evidence": "x = 1",
                "suggestion": "fix",
            }
        )

        code, out, _ = run_parse_in_cwd(
            self._wrap_json(review),
            cwd=tmp_path,
            env_extra={"GH_DIFF_FILE": str(diff)},
        )
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "WARN"
        assert data["findings"][0]["severity"] == "major"
        assert data["findings"][0]["_evidence_verified"] is True


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
    assert data["verdict"] == "SKIP"  # Parse failures are non-blocking
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
    assert data["verdict"] == "SKIP"  # Parse failures are non-blocking
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
    assert data["verdict"] == "SKIP"  # Parse failures are non-blocking
    assert data["confidence"] == 0.0


def test_root_not_object():
    """JSON array at root triggers fallback (note: regex only matches {}, so array is 'no block')."""
    code, out, _ = run_parse('```json\n[1, 2, 3]\n```')
    assert code == 0
    data = json.loads(out)
    assert data["verdict"] == "SKIP"  # Changed: extract_json_block regex only matches objects, not arrays
    assert data["confidence"] == 0.0


def test_missing_reviewer_field_salvaged():
    """Model output missing reviewer/perspective fields is salvaged by injecting known values."""
    # Reproduces the exact scenario from issue #175: model returns valid review
    # JSON but omits the "reviewer" root field.
    incomplete = json.dumps({
        "verdict": "PASS",
        "confidence": 0.85,
        "summary": "Code looks clean",
        "findings": [],
        "stats": {"files_reviewed": 3, "files_with_issues": 0,
                  "critical": 0, "major": 0, "minor": 0, "info": 0},
    })
    code, out, _ = run_parse(
        f"```json\n{incomplete}\n```",
        env_extra={"REVIEWER_NAME": "VULCAN", "PERSPECTIVE": "performance"},
    )
    assert code == 0
    data = json.loads(out)
    # Should be salvaged with injected fields, NOT a SKIP/FAIL fallback.
    assert data["verdict"] == "PASS"
    assert data["reviewer"] == "VULCAN"
    assert data["perspective"] == "performance"
    assert data["confidence"] == 0.85


def test_missing_reviewer_only_salvaged():
    """Model output missing only 'reviewer' is salvaged; 'perspective' present."""
    incomplete = json.dumps({
        "perspective": "security",
        "verdict": "WARN",
        "confidence": 0.75,
        "summary": "Auth concern",
        "findings": [{
            "severity": "major", "category": "auth", "file": "auth.py",
            "line": 10, "title": "Weak check", "description": "d", "suggestion": "s",
        }],
        "stats": {"files_reviewed": 1, "files_with_issues": 1,
                  "critical": 0, "major": 1, "minor": 0, "info": 0},
    })
    code, out, _ = run_parse(
        f"```json\n{incomplete}\n```",
        env_extra={"REVIEWER_NAME": "SENTINEL"},
    )
    assert code == 0
    data = json.loads(out)
    assert data["verdict"] == "WARN"
    assert data["reviewer"] == "SENTINEL"
    assert data["perspective"] == "security"


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
        """Scratchpad without JSON block but with ## Verdict: PASS header is treated as SKIP (non-blocking)."""
        code, out, _ = run_parse_file(
            FIXTURES / "sample-scratchpad-partial.md",
            env_extra={"REVIEWER_NAME": "APOLLO"},
        )
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert data["reviewer"] == "APOLLO"
        assert data["confidence"] < 0.5  # low confidence for partial

    def test_partial_scratchpad_defaults_to_warn(self):
        """Scratchpad without JSON block or verdict header is treated as SKIP (non-blocking)."""
        # Write a scratchpad with investigation notes but no verdict header
        partial_text = "# Review\n\n## Investigation Notes\n- Checked files\n- Found nothing yet\n"
        code, out, _ = run_parse(partial_text, env_extra={"REVIEWER_NAME": "TEST"})
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"

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


class TestRawReviewPreservation:
    """Tests for raw_review field in fallback verdicts."""

    def test_agentic_narration_is_stripped_and_not_surfaced(self):
        """Agentic 'I'll start by...' traces should not be treated as substantive output."""
        agentic = (
            "I'll start by reading the PR diff to understand the changes, then investigate the repository context for security implications. "
            "Now I need to create the security review document and examine the changes more closely. "
            "Let me first create the initial review document and examine the changes more closely. "
        ) * 10
        assert len(agentic.strip()) > 500  # precondition
        code, out, _ = run_parse(agentic, env_extra={"REVIEWER_NAME": "SENTINEL"})
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert "raw_review" not in data  # scrubbed to empty

    def test_scratchpad_with_agentic_preamble_strips_preamble_only(self):
        """Scratchpad partial reviews keep the useful content but drop agentic preambles."""
        scratchpad = (
            "I'll start by reading the PR diff to understand the changes.\n"
            "# Review\n\n"
            "## Investigation Notes\n"
            "- Checked the diff\n"
            "- No security issues found\n\n"
            "## Verdict: PASS\n"
            "No issues found.\n"
        )
        code, out, _ = run_parse(scratchpad, env_extra={"REVIEWER_NAME": "SENTINEL"})
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert "raw_review" in data
        assert "I'll start by reading" not in data["raw_review"]
        assert "Investigation Notes" in data["raw_review"]

    def test_substantive_raw_text_produces_warn_with_raw_review(self):
        """Text >500 chars without JSON block upgrades to WARN and includes raw_review."""
        long_text = "This is a detailed review. " * 30  # ~810 chars
        code, out, _ = run_parse(long_text, env_extra={"REVIEWER_NAME": "APOLLO"})
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "WARN"
        assert data["confidence"] == 0.3
        assert "raw_review" in data
        assert "detailed review" in data["raw_review"]

    def test_short_raw_text_stays_skip_with_raw_review(self):
        """Text <=500 chars without JSON block stays SKIP but still includes raw_review."""
        short_text = "Brief review output."
        code, out, _ = run_parse(short_text, env_extra={"REVIEWER_NAME": "APOLLO"})
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert data.get("raw_review") == short_text

    def test_empty_text_has_no_raw_review(self):
        """Empty text does not include raw_review field."""
        code, out, _ = run_parse("", env_extra={"REVIEWER_NAME": "APOLLO"})
        assert code == 0
        data = json.loads(out)
        assert "raw_review" not in data

    def test_scratchpad_fallback_includes_raw_review(self):
        """Scratchpad without JSON block includes raw_review in fallback."""
        scratchpad = (
            "# Review\n\n"
            "## Investigation Notes\n"
            "- Checked all files for correctness issues\n"
            "- Found no significant problems\n"
            "- Code follows standard patterns\n\n"
            "## Verdict: PASS\n"
            "No issues found.\n"
        )
        code, out, _ = run_parse(scratchpad, env_extra={"REVIEWER_NAME": "APOLLO"})
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert "raw_review" in data
        assert "Investigation Notes" in data["raw_review"]

    def test_raw_review_truncated_at_50kb(self):
        """raw_review field is capped at 50,000 characters."""
        huge_text = "x" * 60000
        code, out, _ = run_parse(huge_text, env_extra={"REVIEWER_NAME": "APOLLO"})
        assert code == 0
        data = json.loads(out)
        assert "raw_review" in data
        assert len(data["raw_review"]) == 50000

    def test_unstructured_text_summary_is_generic(self):
        """Unstructured (non-JSON) output should not leak raw analysis into summary."""
        text = (
            "# Review\n\n## Summary\nThe code looks good overall.\n\n"
            "## Details\n" + "This is detailed analysis of the code. " * 20
        )
        assert len(text.strip()) > 500  # precondition
        code, out, _ = run_parse(text, env_extra={"REVIEWER_NAME": "APOLLO"})
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "WARN"
        assert "unstructured" in data["summary"].lower()
        assert "looks good" not in data["summary"].lower()

    def test_extract_review_summary_with_verdict_header(self):
        """Text with ## Verdict: header is treated as scratchpad and is SKIP (non-blocking)."""
        text = (
            "# Review\n\n## Verdict: PASS\nNo issues found in the codebase.\n\n"
            "## Analysis\n" + "Checked various code paths for problems. " * 20
        )
        assert len(text.strip()) > 500  # precondition
        code, out, _ = run_parse(text, env_extra={"REVIEWER_NAME": "APOLLO"})
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert "raw_review" in data

    def test_substantive_warn_fallback_has_info_finding(self):
        """WARN fallback for substantive raw text includes a parse-failure info finding."""
        long_text = "This is a detailed review. " * 30  # ~810 chars
        code, out, _ = run_parse(long_text, env_extra={"REVIEWER_NAME": "APOLLO"})
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "WARN"
        assert len(data["findings"]) == 1
        finding = data["findings"][0]
        assert finding["severity"] == "info"
        assert finding["category"] == "parse-failure"
        assert "machine-parseable" in finding["title"]
        assert data["stats"]["info"] == 1

    def test_scratchpad_fallback_has_info_finding(self):
        """Scratchpad fallback without JSON block includes a parse-failure info finding."""
        scratchpad = (
            "# Review\n\n"
            "## Investigation Notes\n"
            "- Checked all files for correctness issues\n"
            "- Found no significant problems\n\n"
            "## Verdict: PASS\n"
            "No issues found.\n"
        )
        code, out, _ = run_parse(scratchpad, env_extra={"REVIEWER_NAME": "APOLLO"})
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert len(data["findings"]) == 1
        finding = data["findings"][0]
        assert finding["severity"] == "info"
        assert finding["category"] == "parse-failure"
        assert data["stats"]["info"] == 1

    def test_skip_fallback_has_no_finding(self):
        """SKIP fallback for short non-parseable text has no findings."""
        code, out, _ = run_parse("Brief output.", env_extra={"REVIEWER_NAME": "APOLLO"})
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "SKIP"
        assert len(data["findings"]) == 0
        assert data["stats"]["info"] == 0


class TestExtractReviewSummaryDirect:
    """Direct unit tests for extract_review_summary() via importlib."""

    @staticmethod
    def _load():
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "parse_review", str(SCRIPT),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.extract_review_summary

    def test_extracts_summary_header(self):
        fn = self._load()
        text = "# Review\n\n## Summary\nThe code looks good.\n\n## Details\nMore content."
        assert fn(text) == "The code looks good."

    def test_extracts_verdict_section_body(self):
        """## Verdict: with content on same line falls through to fallback."""
        fn = self._load()
        text = "# Review\n\n## Verdict: PASS\nNo issues found.\n\n## Analysis\nStuff."
        # The regex requires \n after the header, but "PASS" is on the same line,
        # so this falls through to the 500-char fallback.
        result = fn(text)
        assert "Verdict: PASS" in result
        assert "No issues found." in result

    def test_extracts_verdict_header_newline(self):
        """## Verdict: followed by a newline then body extracts correctly."""
        fn = self._load()
        text = "# Review\n\n## Verdict:\nPASS - No issues found.\n\n## Analysis\nStuff."
        assert fn(text) == "PASS - No issues found."

    def test_prefers_summary_over_verdict(self):
        fn = self._load()
        text = "# Review\n\n## Summary\nFirst section.\n\n## Verdict: PASS\nSecond section."
        assert fn(text) == "First section."

    def test_fallback_to_first_500_chars(self):
        fn = self._load()
        text = "No headers here. " * 50
        result = fn(text)
        assert len(result) <= 500
        assert result == text.strip()[:500]

    def test_empty_string(self):
        fn = self._load()
        assert fn("") == ""

    def test_truncates_long_section(self):
        fn = self._load()
        long_body = "x" * 1000
        text = f"# Review\n\n## Summary\n{long_body}\n\n## Details\nMore."
        result = fn(text)
        assert len(result) == 500
        assert result == long_body[:500]


class TestSpeculativeSuggestionDowngrade:
    """Tests for suggestion_verified field (no longer affects severity)."""

    def test_suggestion_verified_false_keeps_severity(self):
        """Finding with suggestion_verified=false keeps its original severity."""
        review = json.dumps({
            "reviewer": "VULCAN", "perspective": "performance", "verdict": "FAIL",
            "confidence": 0.9, "summary": "Performance concern",
            "findings": [{
                "severity": "major",
                "category": "unbounded-query",
                "file": "src/api.py",
                "line": 42,
                "title": "loadConversation fetches all messages without limit",
                "description": "Unbounded query could be slow at scale.",
                "suggestion": "Add pagination support.",
                "suggestion_verified": False,
            }],
            "stats": {"files_reviewed": 1, "files_with_issues": 1,
                      "critical": 0, "major": 1, "minor": 0, "info": 0}
        })
        code, out, _ = run_parse(f"```json\n{review}\n```")
        assert code == 0
        data = json.loads(out)
        # suggestion_verified=false no longer demotes severity
        assert data["findings"][0]["severity"] == "major"
        assert not data["findings"][0]["title"].startswith("[speculative] ")
        assert "_speculative_downgraded" not in data["findings"][0]
        # 1 major → WARN
        assert data["verdict"] == "WARN"

    def test_suggestion_verified_true_keeps_severity(self):
        """Finding with suggestion_verified=true keeps original severity."""
        review = json.dumps({
            "reviewer": "VULCAN", "perspective": "performance", "verdict": "WARN",
            "confidence": 0.9, "summary": "N+1 query found",
            "findings": [{
                "severity": "major",
                "category": "n-plus-one",
                "file": "src/api.py",
                "line": 67,
                "title": "N+1 query in user listing",
                "description": "forEach fires one query per user.",
                "suggestion": "Use batch query.",
                "suggestion_verified": True,
            }],
            "stats": {"files_reviewed": 1, "files_with_issues": 1,
                      "critical": 0, "major": 1, "minor": 0, "info": 0}
        })
        code, out, _ = run_parse(f"```json\n{review}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["findings"][0]["severity"] == "major"
        assert not data["findings"][0]["title"].startswith("[speculative] ")
        assert data["verdict"] == "WARN"

    def test_missing_suggestion_verified_keeps_severity(self):
        """Backward compat: findings without suggestion_verified are not downgraded."""
        review = json.dumps({
            "reviewer": "VULCAN", "perspective": "performance", "verdict": "WARN",
            "confidence": 0.9, "summary": "Issue found",
            "findings": [{
                "severity": "major",
                "category": "n-plus-one",
                "file": "src/api.py",
                "line": 67,
                "title": "N+1 query",
                "description": "desc",
                "suggestion": "Use batch query.",
            }],
            "stats": {"files_reviewed": 1, "files_with_issues": 1,
                      "critical": 0, "major": 1, "minor": 0, "info": 0}
        })
        code, out, _ = run_parse(f"```json\n{review}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["findings"][0]["severity"] == "major"
        assert data["verdict"] == "WARN"

    def test_two_majors_one_speculative_both_count(self):
        """Both findings count regardless of suggestion_verified; 2 majors → FAIL."""
        review = json.dumps({
            "reviewer": "VULCAN", "perspective": "performance", "verdict": "FAIL",
            "confidence": 0.9, "summary": "Two major issues",
            "findings": [
                {
                    "severity": "major",
                    "category": "unbounded-query",
                    "file": "src/api.py",
                    "line": 42,
                    "title": "Unbounded query",
                    "description": "desc",
                    "suggestion": "Add pagination.",
                    "suggestion_verified": False,
                },
                {
                    "severity": "major",
                    "category": "n-plus-one",
                    "file": "src/api.py",
                    "line": 67,
                    "title": "N+1 query",
                    "description": "desc",
                    "suggestion": "Use batch query.",
                    "suggestion_verified": True,
                },
            ],
            "stats": {"files_reviewed": 1, "files_with_issues": 1,
                      "critical": 0, "major": 2, "minor": 0, "info": 0}
        })
        code, out, _ = run_parse(f"```json\n{review}\n```")
        assert code == 0
        data = json.loads(out)
        # Both majors count — suggestion_verified no longer demotes
        assert data["stats"]["major"] == 2
        assert data["stats"]["info"] == 0
        # 2 majors → FAIL
        assert data["verdict"] == "FAIL"

    def test_speculative_critical_keeps_severity(self):
        """Critical findings keep severity even if suggestion is unverified."""
        review = json.dumps({
            "reviewer": "VULCAN", "perspective": "performance", "verdict": "FAIL",
            "confidence": 0.9, "summary": "Critical perf issue",
            "findings": [{
                "severity": "critical",
                "category": "delete-replace",
                "file": "src/gains.py",
                "line": 10,
                "title": "Full delete+insert on every upload",
                "description": "Replaces all gains on each upload.",
                "suggestion": "Use incremental UPSERT.",
                "suggestion_verified": False,
            }],
            "stats": {"files_reviewed": 1, "files_with_issues": 1,
                      "critical": 1, "major": 0, "minor": 0, "info": 0}
        })
        code, out, _ = run_parse(f"```json\n{review}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["findings"][0]["severity"] == "critical"
        assert data["stats"]["critical"] == 1
        assert data["stats"]["info"] == 0
        assert data["verdict"] == "FAIL"

    def test_info_severity_not_downgraded(self):
        """Info findings with suggestion_verified=false are not re-downgraded."""
        review = json.dumps({
            "reviewer": "VULCAN", "perspective": "performance", "verdict": "PASS",
            "confidence": 0.9, "summary": "Minor observation",
            "findings": [{
                "severity": "info",
                "category": "micro-opt",
                "file": "src/utils.py",
                "line": 3,
                "title": "Could use Map",
                "description": "desc",
                "suggestion": "Use Map instead of object.",
                "suggestion_verified": False,
            }],
            "stats": {"files_reviewed": 1, "files_with_issues": 0,
                      "critical": 0, "major": 0, "minor": 0, "info": 1}
        })
        code, out, _ = run_parse(f"```json\n{review}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["findings"][0]["severity"] == "info"
        assert not data["findings"][0]["title"].startswith("[speculative] ")
        assert data["verdict"] == "PASS"


class TestStatsValidation:
    """Tests for validating LLM-reported stats against actual findings (#16)."""

    def test_matching_stats_no_discrepancy(self):
        """When LLM stats match actual findings, no discrepancy is reported."""
        review = json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness", "verdict": "WARN",
            "confidence": 0.9, "summary": "One major issue",
            "findings": [{
                "severity": "major",
                "category": "bug",
                "file": "app.py",
                "line": 10,
                "title": "Bug found",
                "description": "desc",
                "suggestion": "fix",
            }],
            "stats": {"files_reviewed": 1, "files_with_issues": 1,
                      "critical": 0, "major": 1, "minor": 0, "info": 0}
        })
        code, out, _ = run_parse(f"```json\n{review}\n```")
        assert code == 0
        data = json.loads(out)
        assert "_stats_discrepancy" not in data

    def test_llm_over_reports_corrected(self):
        """When LLM reports more issues than actually exist, stats are corrected."""
        review = json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness", "verdict": "WARN",
            "confidence": 0.9, "summary": "Issues found",
            "findings": [{
                "severity": "major",
                "category": "bug",
                "file": "app.py",
                "line": 10,
                "title": "Bug found",
                "description": "desc",
                "suggestion": "fix",
            }],
            "stats": {"files_reviewed": 5, "files_with_issues": 3,
                      "critical": 2, "major": 3, "minor": 1, "info": 0}
        })
        code, out, _ = run_parse(f"```json\n{review}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["stats"]["critical"] == 0
        assert data["stats"]["major"] == 1
        assert data["stats"]["minor"] == 0
        assert data["stats"]["info"] == 0
        assert data["_stats_discrepancy"]["discrepancy"] is True
        assert data["_stats_discrepancy"]["reported"]["critical"] == 2
        assert data["_stats_discrepancy"]["actual"]["critical"] == 0

    def test_llm_under_reports_corrected(self):
        """When LLM reports fewer issues than actually exist, stats are corrected."""
        review = json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness", "verdict": "PASS",
            "confidence": 0.9, "summary": "Looks fine",
            "findings": [
                {
                    "severity": "major",
                    "category": "bug",
                    "file": "app.py",
                    "line": 10,
                    "title": "Bug 1",
                    "description": "desc",
                    "suggestion": "fix",
                },
                {
                    "severity": "minor",
                    "category": "style",
                    "file": "utils.py",
                    "line": 5,
                    "title": "Style issue",
                    "description": "desc",
                    "suggestion": "fix",
                },
            ],
            "stats": {"files_reviewed": 1, "files_with_issues": 0,
                      "critical": 0, "major": 0, "minor": 0, "info": 0}
        })
        code, out, _ = run_parse(f"```json\n{review}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["stats"]["major"] == 1
        assert data["stats"]["minor"] == 1
        assert data["_stats_discrepancy"]["discrepancy"] is True
        assert data["_stats_discrepancy"]["reported"]["major"] == 0
        assert data["_stats_discrepancy"]["actual"]["major"] == 1

    def test_zero_findings_stats_zeroed(self):
        """When there are zero findings, all severity stats should be zero."""
        review = json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness", "verdict": "PASS",
            "confidence": 0.9, "summary": "All clean",
            "findings": [],
            "stats": {"files_reviewed": 5, "files_with_issues": 2,
                      "critical": 1, "major": 1, "minor": 1, "info": 1}
        })
        code, out, _ = run_parse(f"```json\n{review}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["stats"]["critical"] == 0
        assert data["stats"]["major"] == 0
        assert data["stats"]["minor"] == 0
        assert data["stats"]["info"] == 0
        assert data["stats"]["files_with_issues"] == 0
        assert data["_stats_discrepancy"]["discrepancy"] is True

    def test_files_with_issues_corrected(self):
        """files_with_issues is corrected to match unique files in findings."""
        review = json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness", "verdict": "WARN",
            "confidence": 0.9, "summary": "Issues",
            "findings": [
                {
                    "severity": "major",
                    "category": "bug",
                    "file": "app.py",
                    "line": 10,
                    "title": "Bug 1",
                    "description": "desc",
                    "suggestion": "fix",
                },
                {
                    "severity": "minor",
                    "category": "style",
                    "file": "app.py",
                    "line": 20,
                    "title": "Style",
                    "description": "desc",
                    "suggestion": "fix",
                },
            ],
            "stats": {"files_reviewed": 3, "files_with_issues": 3,
                      "critical": 0, "major": 1, "minor": 1, "info": 0}
        })
        code, out, _ = run_parse(f"```json\n{review}\n```")
        assert code == 0
        data = json.loads(out)
        assert data["stats"]["files_with_issues"] == 1
        assert data["_stats_discrepancy"]["discrepancy"] is True

    def test_discrepancy_logged_to_stderr(self):
        """Stats discrepancy is logged to stderr."""
        review = json.dumps({
            "reviewer": "APOLLO", "perspective": "correctness", "verdict": "PASS",
            "confidence": 0.9, "summary": "Clean",
            "findings": [],
            "stats": {"files_reviewed": 1, "files_with_issues": 1,
                      "critical": 1, "major": 0, "minor": 0, "info": 0}
        })
        code, out, err = run_parse(f"```json\n{review}\n```")
        assert code == 0
        assert "stats discrepancy" in err.lower()


class TestDirectJsonInput:
    """Tests for the structured-output extraction path.

    When parse-review.py receives bare JSON (no ```json``` fences), it should
    parse it directly — this is the structured-verdict path from extract-verdict.py.
    """

    def _make_verdict(self, **overrides) -> dict:
        base = {
            "reviewer": "trace",
            "perspective": "correctness",
            "verdict": "PASS",
            "confidence": 0.9,
            "summary": "Looks good.",
            "findings": [],
            "stats": {
                "files_reviewed": 2,
                "files_with_issues": 0,
                "critical": 0,
                "major": 0,
                "minor": 0,
                "info": 0,
            },
        }
        base.update(overrides)
        return base

    def test_bare_json_parsed_without_fences(self):
        """Direct JSON (no ```json``` wrapper) is accepted on the structured-output path."""
        verdict = self._make_verdict()
        code, out, err = run_parse(json.dumps(verdict))
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "PASS"
        assert data["reviewer"] == "trace"

    def test_bare_json_with_findings_passes_validation(self):
        """Direct JSON with findings validates correctly and verdict consistency is enforced."""
        # A single major finding → WARN (enforce_verdict_consistency recomputes from findings)
        verdict = self._make_verdict(
            verdict="WARN",
            confidence=0.85,
            findings=[{
                "severity": "major",
                "category": "correctness",
                "file": "src/main.py",
                "line": 42,
                "title": "Off-by-one",
                "description": "Loop bound is wrong.",
                "suggestion": "Use < not <=.",
                "evidence": "for i in range(0, n+1):",
            }],
            stats={
                "files_reviewed": 1,
                "files_with_issues": 1,
                "critical": 0, "major": 1, "minor": 0, "info": 0,
            },
        )
        code, out, err = run_parse(json.dumps(verdict))
        assert code == 0
        data = json.loads(out)
        # enforce_verdict_consistency: 1 major → WARN
        assert data["verdict"] == "WARN"
        assert len(data["findings"]) == 1

    def test_bare_json_with_leading_whitespace(self):
        """Bare JSON with leading whitespace (e.g. pretty-printed) is still accepted."""
        verdict = self._make_verdict()
        indented = "\n  " + json.dumps(verdict, indent=2).replace("\n", "\n  ")
        # Only works if starts with { after strip — JSON.dumps always starts with {
        code, out, _ = run_parse(json.dumps(verdict, indent=2))
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "PASS"

    def test_fenced_json_still_works(self):
        """Existing fenced-block path is not broken by the new direct path."""
        verdict = self._make_verdict(verdict="FAIL", confidence=0.95,
                                     findings=[{
                                         "severity": "critical",
                                         "category": "correctness",
                                         "file": "app.py",
                                         "line": 1,
                                         "title": "Null deref",
                                         "description": "desc",
                                         "suggestion": "fix",
                                     }],
                                     stats={"files_reviewed": 1, "files_with_issues": 1,
                                            "critical": 1, "major": 0, "minor": 0, "info": 0})
        wrapped = f"Some prose\n\n```json\n{json.dumps(verdict)}\n```\n"
        code, out, _ = run_parse(wrapped)
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "FAIL"


class TestOptionalSuggestion:
    """Regression: finding.suggestion is optional (issue #274).

    parse-review.py previously required 'suggestion' on every finding.
    This caused valid PASS reviews to become SKIP when the model omitted it.
    """

    def _make_pass_verdict(self, findings: list[dict]) -> str:
        verdict = {
            "reviewer": "atlas",
            "perspective": "architecture",
            "verdict": "PASS",
            "confidence": 0.9,
            "summary": "No architectural issues.",
            "findings": findings,
            "stats": {
                "files_reviewed": 2,
                "files_with_issues": len(findings),
                "critical": 0,
                "major": 0,
                "minor": 0,
                "info": len(findings),
            },
        }
        return f"```json\n{json.dumps(verdict)}\n```"

    def test_pass_verdict_without_suggestion_parses_to_pass(self):
        """PASS review with finding that lacks 'suggestion' must parse as PASS, not SKIP."""
        finding_no_suggestion = {
            "severity": "info",
            "category": "style",
            "file": "main.py",
            "line": 10,
            "title": "Minor style note",
            "description": "Consider renaming this variable.",
            # 'suggestion' intentionally omitted
        }
        code, out, _ = run_parse(self._make_pass_verdict([finding_no_suggestion]))
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "PASS", f"Expected PASS, got {data['verdict']}: {data.get('summary')}"

    def test_backfills_empty_suggestion_string(self):
        """Missing 'suggestion' is backfilled to '' so downstream consumers always have the key."""
        finding_no_suggestion = {
            "severity": "info",
            "category": "style",
            "file": "main.py",
            "line": 10,
            "title": "Minor style note",
            "description": "Consider renaming.",
        }
        code, out, _ = run_parse(self._make_pass_verdict([finding_no_suggestion]))
        assert code == 0
        data = json.loads(out)
        assert data["findings"][0]["suggestion"] == ""

    def test_existing_suggestion_preserved(self):
        """Findings that include 'suggestion' are unaffected."""
        finding_with_suggestion = {
            "severity": "info",
            "category": "style",
            "file": "main.py",
            "line": 10,
            "title": "Minor style note",
            "description": "Consider renaming.",
            "suggestion": "Use descriptive_name instead.",
        }
        code, out, _ = run_parse(self._make_pass_verdict([finding_with_suggestion]))
        assert code == 0
        data = json.loads(out)
        assert data["findings"][0]["suggestion"] == "Use descriptive_name instead."

    def test_mixed_findings_some_with_some_without_suggestion(self):
        """Verdicts with mixed findings (some with, some without 'suggestion') parse correctly."""
        findings = [
            {
                "severity": "info",
                "category": "style",
                "file": "a.py",
                "line": 1,
                "title": "No suggestion",
                "description": "desc",
            },
            {
                "severity": "info",
                "category": "style",
                "file": "b.py",
                "line": 2,
                "title": "Has suggestion",
                "description": "desc",
                "suggestion": "do this",
            },
        ]
        code, out, _ = run_parse(self._make_pass_verdict(findings))
        assert code == 0
        data = json.loads(out)
        assert data["verdict"] == "PASS"
        assert data["findings"][0]["suggestion"] == ""
        assert data["findings"][1]["suggestion"] == "do this"
