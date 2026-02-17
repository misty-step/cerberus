import json
import os
import subprocess
import sys
from pathlib import Path

from lib.render_council_comment import (
    collect_hotspots,
    collect_issue_groups,
    count_findings,
    detect_skip_banner,
    normalize_severity,
    normalize_verdict,
    render_comment,
)

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "render-council-comment.py"


def run_render(tmp_path: Path, council: dict, env_extra: dict | None = None) -> tuple[int, str, str]:
    council_path = tmp_path / "council.json"
    output_path = tmp_path / "comment.md"
    council_path.write_text(json.dumps(council), encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "misty-step/cerberus",
            "GITHUB_RUN_ID": "12345",
            "GH_HEAD_SHA": "abcdef1234567890",
            "PR_CHANGED_FILES": "7",
            "PR_ADDITIONS": "120",
            "PR_DELETIONS": "44",
            "CERBERUS_VERSION": "v1-test",
            "GH_OVERRIDE_POLICY": "pr_author",
            "FAIL_ON_VERDICT": "true",
        }
    )
    if env_extra:
        env.update(env_extra)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--council-json",
            str(council_path),
            "--output",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    body = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    return result.returncode, body, result.stderr


def test_renders_scannable_header_and_reviewer_details(tmp_path: Path) -> None:
    council = {
        "verdict": "FAIL",
        "summary": "2 reviewers. Failures: 1, warnings: 0, skipped: 0.",
        "reviewers": [
            {
                "reviewer": "VULCAN",
                "perspective": "performance",
                "reviewer_description": "Performance & Scalability — Think at runtime.",
                "verdict": "FAIL",
                "confidence": 0.82,
                "summary": "N+1 query in hot path.",
                "runtime_seconds": 65,
                "findings": [
                    {
                        "severity": "major",
                        "category": "performance",
                        "file": "src/service.py",
                        "line": 42,
                        "title": "N+1 query in request loop",
                        "description": "Loop issues one query per row.",
                        "suggestion": "Batch load related rows.",
                    }
                ],
                "stats": {"critical": 0, "major": 1, "minor": 0, "info": 0},
            },
            {
                "reviewer": "APOLLO",
                "perspective": "correctness",
                "reviewer_description": "Correctness & Logic — Find the bug.",
                "verdict": "PASS",
                "confidence": 0.93,
                "summary": "No correctness regressions.",
                "runtime_seconds": 12,
                "findings": [],
                "stats": {"critical": 0, "major": 0, "minor": 0, "info": 0},
            },
        ],
        "stats": {"total": 2, "pass": 1, "warn": 0, "fail": 1, "skip": 0},
        "override": {"used": False},
    }

    code, body, err = run_render(tmp_path, council)

    assert code == 0, err
    assert "<!-- cerberus:council -->" in body
    assert "## ❌ Council Verdict: FAIL" in body
    assert "**Summary:** 1/2 reviewers passed. 1 failed (Performance & Scalability)." in body
    assert "**Review Scope:** 7 files changed, +120 / -44 lines" in body
    assert "### Reviewer Overview" in body
    assert "<summary>(click to expand)</summary>" in body
    assert "Vulcan" in body
    assert "runtime `1m 5s`" in body
    assert "Reviewer details (click to expand)" in body
    assert "blob/abcdef1234567890/src/service.py#L42" in body
    assert "/council override sha=abcdef123456" in body


def test_renders_fix_order_and_hotspots_on_warn(tmp_path: Path) -> None:
    council = {
        "verdict": "WARN",
        "summary": "3 reviewers. Failures: 0, warnings: 1, skipped: 0.",
        "reviewers": [
            {
                "reviewer": "APOLLO",
                "perspective": "correctness",
                "verdict": "PASS",
                "confidence": 0.9,
                "summary": "ok",
                "runtime_seconds": 10,
                "findings": [
                    {
                        "severity": "major",
                        "category": "bug",
                        "file": "src/hot1.py",
                        "line": 10,
                        "title": "Shared issue",
                        "description": "short",
                        "suggestion": "short fix",
                    },
                    {
                        "severity": "major",
                        "category": "bug",
                        "file": "src/hot2.py",
                        "line": 3,
                        "title": "Solo issue",
                        "description": "only one reviewer",
                        "suggestion": "fix it",
                    },
                ],
                "stats": {"critical": 0, "major": 2, "minor": 0, "info": 0},
            },
            {
                "reviewer": "ATHENA",
                "perspective": "architecture",
                "verdict": "WARN",
                "confidence": 0.8,
                "summary": "one issue",
                "runtime_seconds": 20,
                "findings": [
                    {
                        "severity": "major",
                        "category": "bug",
                        "file": "src/hot1.py",
                        "line": 10,
                        "title": "Shared issue",
                        "description": "a second reviewer",
                        "suggestion": "this is a much longer suggested fix that should win",
                    },
                    {
                        "severity": "minor",
                        "category": "style",
                        "file": "src/hot1.py",
                        "line": 99,
                        "title": "Minor nit",
                        "description": "nit",
                        "suggestion": "",
                    },
                ],
                "stats": {"critical": 0, "major": 1, "minor": 1, "info": 0},
            },
            {
                "reviewer": "CASSANDRA",
                "perspective": "testing",
                "verdict": "PASS",
                "confidence": 0.85,
                "summary": "ok",
                "runtime_seconds": 15,
                "findings": [
                    {
                        "severity": "minor",
                        "category": "tests",
                        "file": "src/hot1.py",
                        "line": 55,
                        "title": "Add coverage",
                        "description": "add tests",
                        "suggestion": "add tests",
                    }
                ],
                "stats": {"critical": 0, "major": 0, "minor": 1, "info": 0},
            },
        ],
        "stats": {"total": 3, "pass": 2, "warn": 1, "fail": 0, "skip": 0},
        "override": {"used": False},
    }

    code, body, err = run_render(tmp_path, council)
    assert code == 0, err
    assert "### Fix Order" in body
    assert "### Hotspots" in body

    fix_section = body.split("### Fix Order", 1)[1].split("### Hotspots", 1)[0]
    first = next(ln for ln in fix_section.splitlines() if ln.startswith("1. "))
    second = next(ln for ln in fix_section.splitlines() if ln.startswith("2. "))
    assert "Shared issue" in first
    assert "Solo issue" in second
    assert "much longer suggested fix" in fix_section

    hot_section = body.split("### Hotspots", 1)[1].split("### Reviewer Overview", 1)[0]
    first_hot = next(ln for ln in hot_section.splitlines() if ln.startswith("- "))
    assert "blob/abcdef1234567890/src/hot1.py" in first_hot


def test_renders_skip_banner_for_credit_exhaustion(tmp_path: Path) -> None:
    council = {
        "verdict": "WARN",
        "summary": "2 reviewers. Failures: 0, warnings: 1, skipped: 1.",
        "reviewers": [
            {
                "reviewer": "SENTINEL",
                "perspective": "security",
                "reviewer_description": "Security & Threat Model — Think like an attacker.",
                "verdict": "SKIP",
                "confidence": 0.0,
                "summary": "Review skipped due to API credits depleted.",
                "runtime_seconds": 3,
                "findings": [
                    {
                        "severity": "info",
                        "category": "api_error",
                        "file": "",
                        "line": 0,
                        "title": "CREDITS_DEPLETED",
                        "description": "",
                        "suggestion": "",
                    }
                ],
                "stats": {"critical": 0, "major": 0, "minor": 0, "info": 1},
            },
            {
                "reviewer": "ATHENA",
                "perspective": "architecture",
                "reviewer_description": "Architecture & Design — Zoom out.",
                "verdict": "WARN",
                "confidence": 0.75,
                "summary": "One major design issue.",
                "runtime_seconds": 41,
                "findings": [],
                "stats": {"critical": 0, "major": 1, "minor": 0, "info": 0},
            },
        ],
        "stats": {"total": 2, "pass": 0, "warn": 1, "fail": 0, "skip": 1},
        "override": {"used": False},
    }

    code, body, err = run_render(tmp_path, council)

    assert code == 0, err
    assert "API credits depleted for one or more reviewers" in body
    assert "**Summary:** 0/2 reviewers passed. 1 warned (Architecture & Design). 1 skipped (Security & Threat Model)." in body


def test_normalize_verdict_defaults_unknown() -> None:
    assert normalize_verdict("PASS") == "PASS"
    assert normalize_verdict("bad") == "WARN"


def test_normalize_severity_defaults_unknown() -> None:
    assert normalize_severity("critical") == "critical"
    assert normalize_severity("MISSING") == "info"


def test_count_findings_uses_stats_block_when_available() -> None:
    council = {
        "reviewers": [
            {"stats": {"critical": 1, "major": 2, "minor": 3, "info": 4}, "findings": []},
            {"stats": {"critical": 0, "major": 1}, "findings": [{"severity": "critical"}]},
        ]
    }
    found = count_findings(council["reviewers"])
    assert found == {"critical": 2, "major": 3, "minor": 3, "info": 4}


def test_detect_skip_banner_for_key_api_error_paths() -> None:
    reviewer = {
        "verdict": "SKIP",
        "summary": "provider returned bad key",
        "findings": [{"category": "api_error", "title": "KEY_INVALID", "file": "", "line": 0}],
    }
    assert "API key error for one or more reviewers" in detect_skip_banner([reviewer])


def test_collect_issue_groups_merges_matching_findings() -> None:
    reviewer_a = {
        "reviewer": "APOLLO",
        "findings": [
            {
                "severity": "major",
                "category": "tests",
                "file": "src/a.py",
                "line": 10,
                "title": "Shared issue",
                "suggestion": "short",
            }
        ],
    }
    reviewer_b = {
        "reviewer": "VULCAN",
        "findings": [
            {
                "severity": "critical",
                "category": "tests",
                "file": "src/a.py",
                "line": 10,
                "title": "Shared issue",
                "suggestion": "longer suggestion",
            },
            {
                "severity": "minor",
                "category": "tests",
                "file": "src/a.py",
                "line": 11,
                "title": "Unique issue",
            },
        ],
    }

    groups = collect_issue_groups([reviewer_a, reviewer_b])
    merged = {(item["file"], item["line"], item["title"]): item for item in groups}

    assert len(groups) == 2
    assert merged[("src/a.py", 10, "Shared issue")]["severity"] == "critical"
    assert merged[("src/a.py", 10, "Shared issue")]["suggestion"] == "longer suggestion"
    assert merged[("src/a.py", 10, "Shared issue")]["reviewers"] == ["APOLLO", "VULCAN"]


def test_collect_hotspots_handles_multiple_reviewers() -> None:
    reviewer_a = {
        "reviewer": "APOLLO",
        "findings": [{"file": "src/a.py", "severity": "major", "title": "One"}],
    }
    reviewer_b = {
        "reviewer": "VULCAN",
        "findings": [
            {"file": "src/a.py", "severity": "critical", "title": "Two"},
            {"file": "src/b.py", "severity": "info", "title": "Three"},
        ],
    }
    hotspots = collect_hotspots([reviewer_a, reviewer_b])
    assert [item["file"] for item in hotspots] == ["src/a.py", "src/b.py"]
    assert hotspots[0]["reviewers"] == ["APOLLO", "VULCAN"]


def test_render_comment_renders_without_stats_or_findings() -> None:
    comment = render_comment({"reviewers": []}, max_findings=3, max_key_findings=2, marker="<!-- test -->")
    assert "<!-- test -->" in comment
    assert "## ✅ Council Verdict: PASS" in comment
    assert "No reviewer verdicts available." in comment


def test_raw_review_is_omitted_and_note_is_present(tmp_path: Path) -> None:
    council = {
        "verdict": "WARN",
        "summary": "1 reviewer warned.",
        "reviewers": [
            {
                "reviewer": "APOLLO",
                "perspective": "correctness",
                "verdict": "WARN",
                "confidence": 0.3,
                "summary": "Partial review — no JSON block.",
                "runtime_seconds": 45,
                "findings": [],
                "stats": {"critical": 0, "major": 0, "minor": 0, "info": 0},
                "raw_review": "## Investigation Notes\n- Checked all files\n- Found minor issue in main.py\n\n## Verdict: WARN\nMinor issues found.",
            },
        ],
        "stats": {"total": 1, "pass": 0, "warn": 1, "fail": 0, "skip": 0},
        "override": {"used": False},
    }

    code, body, err = run_render(tmp_path, council)

    assert code == 0, err
    assert "produced unstructured output" in body
    assert "Raw output is preserved" in body
    assert "Investigation Notes" not in body


def test_no_raw_review_block_when_absent(tmp_path: Path) -> None:
    council = {
        "verdict": "PASS",
        "summary": "1 reviewer passed.",
        "reviewers": [
            {
                "reviewer": "APOLLO",
                "perspective": "correctness",
                "verdict": "PASS",
                "confidence": 0.9,
                "summary": "No issues.",
                "runtime_seconds": 10,
                "findings": [],
                "stats": {"critical": 0, "major": 0, "minor": 0, "info": 0},
            },
        ],
        "stats": {"total": 1, "pass": 1, "warn": 0, "fail": 0, "skip": 0},
        "override": {"used": False},
    }

    code, body, err = run_render(tmp_path, council)

    assert code == 0, err
    assert "Full review output" not in body
    assert "Reviewer details (click to expand)" not in body


def test_increased_truncation_limits(tmp_path: Path) -> None:
    long_desc = "D" * 500  # Would be truncated at 220 before, now fits in 1000
    long_sugg = "S" * 500
    long_title = "T" * 150  # Would be truncated at 100 before, now fits in 200
    council = {
        "verdict": "WARN",
        "summary": "Test truncation limits.",
        "reviewers": [
            {
                "reviewer": "VULCAN",
                "perspective": "performance",
                "verdict": "WARN",
                "confidence": 0.85,
                "summary": "Found issue.",
                "runtime_seconds": 30,
                "findings": [
                    {
                        "severity": "major",
                        "category": "performance",
                        "file": "app.py",
                        "line": 1,
                        "title": long_title,
                        "description": long_desc,
                        "suggestion": long_sugg,
                    }
                ],
                "stats": {"critical": 0, "major": 1, "minor": 0, "info": 0},
            },
        ],
        "stats": {"total": 1, "pass": 0, "warn": 1, "fail": 0, "skip": 0},
        "override": {"used": False},
    }

    code, body, err = run_render(tmp_path, council)

    assert code == 0, err
    # Full strings should appear without truncation ellipsis
    assert long_desc in body
    assert long_sugg in body
    assert long_title in body


def test_renders_model_in_reviewer_details(tmp_path: Path) -> None:
    council = {
        "verdict": "PASS",
        "summary": "1 reviewer. Failures: 0, warnings: 0, skipped: 0.",
        "reviewers": [
            {
                "reviewer": "APOLLO",
                "perspective": "correctness",
                "verdict": "PASS",
                "confidence": 0.93,
                "summary": "No issues.",
                "runtime_seconds": 12,
                "findings": [],
                "stats": {"critical": 0, "major": 0, "minor": 0, "info": 0},
                "model_used": "openrouter/moonshotai/kimi-k2.5",
                "primary_model": "openrouter/moonshotai/kimi-k2.5",
                "fallback_used": False,
            },
        ],
        "stats": {"total": 1, "pass": 1, "warn": 0, "fail": 0, "skip": 0},
        "override": {"used": False},
    }

    code, body, err = run_render(tmp_path, council)

    assert code == 0, err
    # Model should appear in reviewer overview
    assert "model `kimi-k2.5`" in body


def test_renders_fallback_model_indicator(tmp_path: Path) -> None:
    council = {
        "verdict": "PASS",
        "summary": "1 reviewer.",
        "reviewers": [
            {
                "reviewer": "SENTINEL",
                "perspective": "security",
                "verdict": "PASS",
                "confidence": 0.88,
                "summary": "No issues.",
                "runtime_seconds": 30,
                "findings": [],
                "stats": {"critical": 0, "major": 0, "minor": 0, "info": 0},
                "model_used": "openrouter/deepseek/deepseek-v3.2",
                "primary_model": "openrouter/moonshotai/kimi-k2.5",
                "fallback_used": True,
            },
        ],
        "stats": {"total": 1, "pass": 1, "warn": 0, "fail": 0, "skip": 0},
        "override": {"used": False},
    }

    code, body, err = run_render(tmp_path, council)

    assert code == 0, err
    assert "`deepseek-v3.2` ↩️ (fallback from `kimi-k2.5`)" in body


def test_no_model_when_metadata_absent(tmp_path: Path) -> None:
    council = {
        "verdict": "PASS",
        "summary": "1 reviewer.",
        "reviewers": [
            {
                "reviewer": "APOLLO",
                "perspective": "correctness",
                "verdict": "PASS",
                "confidence": 0.93,
                "summary": "No issues.",
                "runtime_seconds": 12,
                "findings": [],
                "stats": {"critical": 0, "major": 0, "minor": 0, "info": 0},
            },
        ],
        "stats": {"total": 1, "pass": 1, "warn": 0, "fail": 0, "skip": 0},
        "override": {"used": False},
    }

    code, body, err = run_render(tmp_path, council)

    assert code == 0, err
    assert "| model " not in body
    assert "- Model:" not in body



def test_renders_override_details_when_present(tmp_path: Path) -> None:
    council = {
        "verdict": "PASS",
        "summary": "Override by owner for abcdef1.",
        "reviewers": [],
        "stats": {"total": 0, "pass": 0, "warn": 0, "fail": 0, "skip": 0},
        "override": {"used": True, "actor": "owner", "sha": "abcdef1", "reason": "False positive"},
    }

    code, body, err = run_render(tmp_path, council)

    assert code == 0, err
    assert "**Override:** active by `owner` on `abcdef1`. Reason: False positive" in body


def test_oversized_comment_strips_raw_review(tmp_path: Path) -> None:
    """Comments exceeding MAX_COMMENT_SIZE truncate reviewer details and add a note."""
    huge_summary = "x" * 70000
    council = {
        "verdict": "WARN",
        "summary": "1 reviewer warned.",
        "reviewers": [
            *[
                {
                    "reviewer": f"R{i}",
                    "perspective": "correctness",
                    "verdict": "WARN",
                    "confidence": 0.3,
                    "summary": huge_summary,
                    "runtime_seconds": 45,
                    "findings": [
                        {
                            "severity": "minor",
                            "category": "test",
                            "file": f"src/file{i}.py",
                            "line": 1,
                            "title": f"Finding {i}",
                            "description": "desc",
                            "suggestion": "sugg",
                        }
                    ],
                    "stats": {"critical": 0, "major": 0, "minor": 0, "info": 0},
                }
                for i in range(40)
            ],
        ],
        "stats": {"total": 40, "pass": 0, "warn": 40, "fail": 0, "skip": 0},
        "override": {"used": False},
    }

    code, body, err = run_render(tmp_path, council)

    assert code == 0, err
    assert len(body) < 65536, f"Comment is {len(body)} bytes, should be under 65536"
    assert "Comment was truncated" in body
    assert "Reviewer details (click to expand)" not in body
    # Structural content should still be present
    assert "## ⚠️ Council Verdict: WARN" in body
    assert "### Reviewer Overview" in body
    assert "<summary>(click to expand)</summary>" in body
    assert "### Key Findings" in body
    assert "<summary>(show less)</summary>" in body
    key_section = body.split("### Key Findings", 1)[1]
    key_section = key_section.split("\n---\n", 1)[0]
    assert key_section.count("**Finding ") == 5
