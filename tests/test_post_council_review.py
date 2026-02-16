import importlib.util
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "post-council-review.py"


def _load():
    spec = importlib.util.spec_from_file_location("post_council_review", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


post_council_review = _load()


def test_collect_inline_findings_filters_dedupes_and_merges() -> None:
    council = {
        "reviewers": [
            {
                "reviewer": "APOLLO",
                "perspective": "correctness",
                "reviewer_description": "Correctness & Logic — Find the bug",
                "findings": [
                    {
                        "severity": "minor",
                        "category": "style",
                        "file": "x.py",
                        "line": 1,
                        "title": "nit",
                        "description": "minor",
                        "suggestion": "",
                        "evidence": "",
                    },
                    {
                        "severity": "major",
                        "category": "Bug",
                        "file": "x.py",
                        "line": 10,
                        "title": "Same  issue",
                        "description": "short",
                        "suggestion": "s",
                        "evidence": "e",
                    },
                ],
            },
            {
                "reviewer": "SENTINEL",
                "perspective": "security",
                "reviewer_description": "Security & Threat Model — Think like an attacker",
                "findings": [
                    {
                        "severity": "critical",
                        "category": "bug",
                        "file": "x.py",
                        "line": 10,
                        "title": "same issue",
                        "description": "this description is longer",
                        "suggestion": "this suggestion is longer too",
                        "evidence": "evidence line 1\nline 2",
                    },
                    {
                        "severity": "major",
                        "category": "bug",
                        "file": "",
                        "line": 99,
                        "title": "missing file is ignored",
                        "description": "",
                        "suggestion": "",
                        "evidence": "",
                    },
                ],
            },
        ]
    }

    out = post_council_review.collect_inline_findings(council)
    assert len(out) == 1
    finding = out[0]
    assert finding["file"] == "x.py"
    assert finding["line"] == 10
    assert finding["severity"] == "critical"  # worst wins
    assert finding["reviewers"] == ["Correctness & Logic", "Security & Threat Model"]
    assert finding["description"] == "this description is longer"
    assert finding["suggestion"] == "this suggestion is longer too"
    assert finding["evidence"] == "evidence line 1\nline 2"


def test_render_inline_comment_includes_collapsed_evidence() -> None:
    finding = {
        "severity": "critical",
        "category": "security",
        "title": "Constant-time compare required",
        "reviewers": ["SENTINEL", "APOLLO", "ATHENA", "VULCAN"],
        "description": "Timing attack risk.",
        "suggestion": "Use constant-time compare.",
        "evidence": "if sig == expected: ok()",
    }

    body = post_council_review.render_inline_comment(finding)

    assert "(SENTINEL, APOLLO, +2)" in body
    assert "Suggestion: Use constant-time compare." in body
    assert "<details>" in body
    assert "<summary>Evidence</summary>" in body
    assert "```text" in body
    assert "if sig == expected: ok()" in body
