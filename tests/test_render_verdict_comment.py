import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lib.render_verdict_comment import (
    classify_skip_reviewer,
    collect_hotspots,
    collect_issue_groups,
    count_findings,
    detect_skip_banner,
    format_skip_diagnostics_table,
    normalize_severity,
    normalize_verdict,
    main as render_verdict_comment_main,
    render_comment,
)

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "render-verdict-comment.py"


def run_render(tmp_path: Path, verdict_data: dict, env_extra: dict | None = None) -> tuple[int, str, str]:
    verdict_path = tmp_path / "verdict.json"
    output_path = tmp_path / "comment.md"
    verdict_path.write_text(json.dumps(verdict_data), encoding="utf-8")

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
            "--verdict-json",
            str(verdict_path),
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
    verdict_data = {
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

    code, body, err = run_render(tmp_path, verdict_data)

    assert code == 0, err
    assert "<!-- cerberus:verdict -->" in body
    assert "## ❌ Cerberus Verdict: FAIL" in body
    assert "**Summary:** 1/2 reviewers passed. 1 failed (Performance & Scalability)." in body
    assert "**Review Scope:** 7 files changed, +120 / -44 lines" in body
    assert "### Reviewer Overview" in body
    assert "<summary>(click to expand)</summary>" in body
    assert "Vulcan" in body
    assert "runtime `1m 5s`" in body
    assert "Reviewer details (click to expand)" in body
    assert "blob/abcdef1234567890/src/service.py#L42" in body
    assert "/cerberus override sha=abcdef123456" in body


def test_exits_nonzero_on_non_object_json(tmp_path: Path) -> None:
    code, body, err = run_render(tmp_path, ["not an object"])

    assert code == 2
    assert body == ""
    assert "expected object" in err


def test_renders_fix_order_and_hotspots_on_warn(tmp_path: Path) -> None:
    verdict_data = {
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

    code, body, err = run_render(tmp_path, verdict_data)
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
    verdict_data = {
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

    code, body, err = run_render(tmp_path, verdict_data)

    assert code == 0, err
    assert "API credits depleted for one or more reviewers" in body
    assert "**Summary:** 0/2 reviewers passed. 1 warned (Architecture & Design). 1 skipped (Security & Threat Model)." in body


def test_renders_wave_summary_and_reviewer_wave_labels(tmp_path: Path) -> None:
    verdict_data = {
        "verdict": "WARN",
        "summary": "3 reviewers. 1 warning.",
        "reviewers": [
            {
                "reviewer": "TRACE",
                "perspective": "correctness",
                "verdict": "PASS",
                "confidence": 0.9,
                "summary": "ok",
                "runtime_seconds": 11,
                "model_wave": "wave1",
                "findings": [],
                "stats": {"critical": 0, "major": 0, "minor": 0, "info": 0},
            },
            {
                "reviewer": "ATLAS",
                "perspective": "architecture",
                "verdict": "WARN",
                "confidence": 0.8,
                "summary": "one issue",
                "runtime_seconds": 19,
                "model_wave": "wave2",
                "findings": [
                    {
                        "severity": "major",
                        "category": "architecture",
                        "file": "src/a.py",
                        "line": 9,
                        "title": "Layer leak",
                        "description": "internal details leak across module boundary",
                        "suggestion": "narrow interface",
                    }
                ],
                "stats": {"critical": 0, "major": 1, "minor": 0, "info": 0},
            },
            {
                "reviewer": "GUARD",
                "perspective": "security",
                "verdict": "PASS",
                "confidence": 0.87,
                "summary": "ok",
                "runtime_seconds": 14,
                "model_wave": "wave3",
                "findings": [],
                "stats": {"critical": 0, "major": 0, "minor": 0, "info": 0},
            },
        ],
        "stats": {"total": 3, "pass": 2, "warn": 1, "fail": 0, "skip": 0},
        "override": {"used": False},
    }

    code, body, err = run_render(tmp_path, verdict_data)
    assert code == 0, err
    assert "### Wave Summary" in body
    assert "**Wave 1**: 1 reviewers | 1 pass | 0 warn | 0 fail | 0 skip | 0 findings" in body
    assert "**Wave 2**: 1 reviewers | 0 pass | 1 warn | 0 fail | 0 skip | 1 findings" in body
    assert "**Wave 3**: 1 reviewers | 1 pass | 0 warn | 0 fail | 0 skip | 0 findings" in body
    assert "wave `Wave 2`" in body
    assert "- Wave: `Wave 2`" in body


def test_normalize_verdict_defaults_unknown() -> None:
    assert normalize_verdict("PASS") == "PASS"
    assert normalize_verdict("bad") == "WARN"


def test_normalize_severity_defaults_unknown() -> None:
    assert normalize_severity("critical") == "critical"
    assert normalize_severity("MISSING") == "info"


def test_count_findings_uses_stats_block_when_available() -> None:
    verdict_data = {
        "reviewers": [
            {"stats": {"critical": 1, "major": 2, "minor": 3, "info": 4}, "findings": []},
            {"stats": {"critical": 0, "major": 1}, "findings": [{"severity": "critical"}]},
        ]
    }
    found = count_findings(verdict_data["reviewers"])
    assert found == {"critical": 1, "major": 3, "minor": 3, "info": 4}


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
    assert merged[("src/a.py", 10, "Shared issue")]["reviewers"] == ["Apollo", "Vulcan"]


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
    assert hotspots[0]["reviewers"] == ["Apollo", "Vulcan"]


def test_render_comment_renders_without_stats_or_findings() -> None:
    comment = render_comment(
        {"verdict": "PASS", "reviewers": []},
        max_findings=3,
        max_key_findings=2,
        marker="<!-- test -->",
    )
    assert "<!-- test -->" in comment
    assert "## ✅ Cerberus Verdict: PASS" in comment
    assert "No reviewer verdicts available." in comment


def test_raw_review_is_omitted_and_note_is_present(tmp_path: Path) -> None:
    verdict_data = {
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

    code, body, err = run_render(tmp_path, verdict_data)

    assert code == 0, err
    assert "produced unstructured output" in body
    assert "Raw output is preserved" in body
    assert "Investigation Notes" not in body


def test_no_raw_review_block_when_absent(tmp_path: Path) -> None:
    verdict_data = {
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

    code, body, err = run_render(tmp_path, verdict_data)

    assert code == 0, err
    assert "Full review output" not in body
    assert "Reviewer details (click to expand)" not in body


def test_increased_truncation_limits(tmp_path: Path) -> None:
    long_desc = "D" * 500  # Would be truncated at 220 before, now fits in 1000
    long_sugg = "S" * 500
    long_title = "T" * 150  # Would be truncated at 100 before, now fits in 200
    verdict_data = {
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

    code, body, err = run_render(tmp_path, verdict_data)

    assert code == 0, err
    # Full strings should appear without truncation ellipsis
    assert long_desc in body
    assert long_sugg in body
    assert long_title in body


def test_renders_model_in_reviewer_details(tmp_path: Path) -> None:
    verdict_data = {
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

    code, body, err = run_render(tmp_path, verdict_data)

    assert code == 0, err
    # Model should appear in reviewer overview
    assert "model `kimi-k2.5`" in body


def test_renders_fallback_model_indicator(tmp_path: Path) -> None:
    verdict_data = {
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

    code, body, err = run_render(tmp_path, verdict_data)

    assert code == 0, err
    assert "`deepseek-v3.2` ↩️ (fallback from `kimi-k2.5`)" in body


def test_no_model_when_metadata_absent(tmp_path: Path) -> None:
    verdict_data = {
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

    code, body, err = run_render(tmp_path, verdict_data)

    assert code == 0, err
    assert "| model " not in body
    assert "- Model:" not in body



def test_renders_override_details_when_present(tmp_path: Path) -> None:
    verdict_data = {
        "verdict": "PASS",
        "summary": "Override by owner for abcdef1.",
        "reviewers": [],
        "stats": {"total": 0, "pass": 0, "warn": 0, "fail": 0, "skip": 0},
        "override": {"used": True, "actor": "owner", "sha": "abcdef1", "reason": "False positive"},
    }

    code, body, err = run_render(tmp_path, verdict_data)

    assert code == 0, err
    assert "**Override:** active by `owner` on `abcdef1`. Reason: False positive" in body


def test_oversized_comment_strips_raw_review(tmp_path: Path) -> None:
    """Comments exceeding MAX_COMMENT_SIZE truncate reviewer details and add a note."""
    huge_summary = "x" * 70000
    verdict_data = {
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

    code, body, err = run_render(tmp_path, verdict_data)

    assert code == 0, err
    assert len(body) < 65536, f"Comment is {len(body)} bytes, should be under 65536"
    assert "Comment was truncated" in body
    assert "Reviewer details (click to expand)" not in body
    # Structural content should still be present
    assert "## ⚠️ Cerberus Verdict: WARN" in body
    assert "### Reviewer Overview" in body
    assert "<summary>(click to expand)</summary>" in body
    assert "### Key Findings" in body
    assert "<summary>(show less)</summary>" in body
    key_section = body.split("### Key Findings", 1)[1]
    key_section = key_section.split("\n---\n", 1)[0]
    assert key_section.count("**Finding ") == 5


def test_main_allows_direct_arg_parsing(tmp_path: Path) -> None:
    verdict_data = {"verdict": "PASS", "stats": {"total": 0, "pass": 0, "warn": 0, "fail": 0, "skip": 0}}
    verdict_path = tmp_path / "verdict.json"
    output_path = tmp_path / "comment.md"
    verdict_path.write_text(json.dumps(verdict_data), encoding="utf-8")

    code = render_verdict_comment_main(
        [
            "--verdict-json",
            str(verdict_path),
            "--output",
            str(output_path),
            "--max-findings",
            "5",
            "--max-key-findings",
            "5",
        ]
    )
    body = output_path.read_text(encoding="utf-8")

    assert code == 0
    assert "<!-- cerberus:verdict -->" in body


_FAIL_COUNCIL = {
    "verdict": "FAIL",
    "summary": "1 reviewer. Failures: 1, warnings: 0, skipped: 0.",
    "reviewers": [
        {
            "reviewer": "APOLLO",
            "perspective": "correctness",
            "verdict": "FAIL",
            "confidence": 0.9,
            "summary": "Bug found.",
            "runtime_seconds": 30,
            "findings": [
                {
                    "severity": "critical",
                    "category": "bug",
                    "file": "src/app.py",
                    "line": 10,
                    "title": "Critical bug",
                    "description": "Bad thing.",
                    "suggestion": "Fix it.",
                }
            ],
            "stats": {"critical": 1, "major": 0, "minor": 0, "info": 0},
        }
    ],
    "stats": {"total": 1, "pass": 0, "warn": 0, "fail": 1, "skip": 0},
    "override": {"used": False},
}


def test_advisory_banner_shown_when_fail_on_verdict_false(tmp_path: Path) -> None:
    code, body, err = run_render(
        tmp_path, _FAIL_COUNCIL, env_extra={"FAIL_ON_VERDICT": "false"}
    )

    assert code == 0, err
    assert "Cerberus Verdict: FAIL (advisory)" in body
    assert "Advisory mode" in body
    assert "fail-on-verdict" in body
    # Standard FAIL header must NOT appear when advisory
    assert "## ❌ Cerberus Verdict: FAIL\n" not in body


def test_no_advisory_banner_when_fail_on_verdict_true(tmp_path: Path) -> None:
    code, body, err = run_render(
        tmp_path, _FAIL_COUNCIL, env_extra={"FAIL_ON_VERDICT": "true"}
    )

    assert code == 0, err
    assert "## ❌ Cerberus Verdict: FAIL" in body
    assert "(advisory)" not in body
    assert "Advisory mode" not in body


def test_advisory_banner_not_shown_for_pass_verdict(tmp_path: Path) -> None:
    pass_verdict_data = {
        "verdict": "PASS",
        "summary": "1 reviewer. Failures: 0.",
        "reviewers": [
            {
                "reviewer": "APOLLO",
                "perspective": "correctness",
                "verdict": "PASS",
                "confidence": 0.95,
                "summary": "All good.",
                "runtime_seconds": 20,
                "findings": [],
                "stats": {"critical": 0, "major": 0, "minor": 0, "info": 0},
            }
        ],
        "stats": {"total": 1, "pass": 1, "warn": 0, "fail": 0, "skip": 0},
        "override": {"used": False},
    }
    code, body, err = run_render(
        tmp_path, pass_verdict_data, env_extra={"FAIL_ON_VERDICT": "false"}
    )

    assert code == 0, err
    assert "(advisory)" not in body
    assert "Advisory mode" not in body


def test_advisory_banner_not_shown_for_warn_verdict(tmp_path: Path) -> None:
    warn_verdict_data = {
        "verdict": "WARN",
        "summary": "1 reviewer. Warnings: 1.",
        "reviewers": [
            {
                "reviewer": "ATHENA",
                "perspective": "architecture",
                "verdict": "WARN",
                "confidence": 0.8,
                "summary": "Minor design issue.",
                "runtime_seconds": 25,
                "findings": [
                    {
                        "severity": "major",
                        "category": "design",
                        "file": "src/app.py",
                        "line": 5,
                        "title": "Coupling issue",
                        "description": "Tight coupling.",
                        "suggestion": "Extract interface.",
                    }
                ],
                "stats": {"critical": 0, "major": 1, "minor": 0, "info": 0},
            }
        ],
        "stats": {"total": 1, "pass": 0, "warn": 1, "fail": 0, "skip": 0},
        "override": {"used": False},
    }
    code, body, err = run_render(
        tmp_path, warn_verdict_data, env_extra={"FAIL_ON_VERDICT": "false"}
    )

    assert code == 0, err
    assert "(advisory)" not in body
    assert "Advisory mode" not in body


_SKIP_COUNCIL = {
    "verdict": "SKIP",
    "summary": "2 reviewers. Failures: 0, warnings: 0, skipped: 2.",
    "reviewers": [
        {
            "reviewer": "trace",
            "perspective": "correctness",
            "verdict": "SKIP",
            "confidence": 0.0,
            "summary": "review skipped due to timeout after 600s.",
            "runtime_seconds": 600,
            "findings": [
                {
                    "severity": "info",
                    "category": "timeout",
                    "file": "",
                    "line": 0,
                    "title": "Reviewer timeout after 600s",
                    "description": "",
                    "suggestion": "",
                }
            ],
            "stats": {"critical": 0, "major": 0, "minor": 0, "info": 1},
        },
        {
            "reviewer": "atlas",
            "perspective": "architecture",
            "verdict": "SKIP",
            "confidence": 0.0,
            "summary": "review skipped due to timeout after 600s.",
            "runtime_seconds": 600,
            "findings": [
                {
                    "severity": "info",
                    "category": "timeout",
                    "file": "",
                    "line": 0,
                    "title": "Reviewer timeout after 600s",
                    "description": "",
                    "suggestion": "",
                }
            ],
            "stats": {"critical": 0, "major": 0, "minor": 0, "info": 1},
        },
    ],
    "stats": {"total": 2, "pass": 0, "warn": 0, "fail": 0, "skip": 2},
    "override": {"used": False},
}


def test_advisory_banner_shown_when_fail_on_skip_false_and_skip_verdict(tmp_path: Path) -> None:
    code, body, err = run_render(
        tmp_path, _SKIP_COUNCIL, env_extra={"FAIL_ON_SKIP": "false"}
    )

    assert code == 0, err
    assert "Cerberus Verdict: SKIP (advisory)" in body
    assert "Advisory mode" in body
    assert "fail-on-skip" in body
    assert "## ⏭️ Cerberus Verdict: SKIP\n" not in body


def test_no_advisory_banner_when_fail_on_skip_true_and_skip_verdict(tmp_path: Path) -> None:
    code, body, err = run_render(
        tmp_path, _SKIP_COUNCIL, env_extra={"FAIL_ON_SKIP": "true"}
    )

    assert code == 0, err
    assert "## ⏭️ Cerberus Verdict: SKIP" in body
    assert "(advisory)" not in body
    assert "Advisory mode" not in body


def test_skip_verdict_shows_skip_advisory_not_fail_advisory(tmp_path: Path) -> None:
    """SKIP verdict with both advisory flags off: skip banner fires, fail banner does not."""
    code, body, err = run_render(
        tmp_path, _SKIP_COUNCIL, env_extra={"FAIL_ON_VERDICT": "false", "FAIL_ON_SKIP": "false"}
    )

    assert code == 0, err
    assert "fail-on-skip" in body
    assert "fail-on-verdict" not in body


def test_main_rejects_invalid_max_findings(tmp_path: Path, capsys) -> None:
    verdict_path = tmp_path / "verdict.json"
    output_path = tmp_path / "comment.md"
    verdict_path.write_text(json.dumps({"verdict": "PASS"}), encoding="utf-8")

    code = render_verdict_comment_main(
        [
            "--verdict-json",
            str(verdict_path),
            "--output",
            str(output_path),
            "--max-findings",
            "0",
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert "max-findings must be >= 1" in captured.err


# ---------------------------------------------------------------------------
# classify_skip_reviewer — unit tests for all 5 error types
# ---------------------------------------------------------------------------

def _skip_reviewer(category: str, title: str, summary: str = "") -> dict:
    return {
        "reviewer": "test",
        "verdict": "SKIP",
        "summary": summary,
        "findings": [{"category": category, "title": title, "file": "", "line": 0}],
    }


def test_classify_skip_reviewer_timeout_with_duration() -> None:
    rv = _skip_reviewer("timeout", "Reviewer timeout after 600s", "review skipped due to timeout after 600s.")
    result = classify_skip_reviewer(rv)
    assert "Timeout" in result["reason"]
    assert "600s" in result["reason"]
    assert "timeout" in result["recovery"].lower()


def test_classify_skip_reviewer_timeout_without_duration() -> None:
    rv = _skip_reviewer("timeout", "Timeout", "review skipped")
    result = classify_skip_reviewer(rv)
    assert "Timeout" in result["reason"]
    assert "timeout" in result["recovery"].lower()


def test_classify_skip_reviewer_auth_error() -> None:
    rv = _skip_reviewer("api_error", "API Error: API_KEY_INVALID")
    result = classify_skip_reviewer(rv)
    assert "Auth" in result["reason"] or "key" in result["reason"].lower()
    assert "key" in result["recovery"].lower()


def test_classify_skip_reviewer_credits_depleted() -> None:
    rv = _skip_reviewer("api_error", "API Error: API_CREDITS_DEPLETED")
    result = classify_skip_reviewer(rv)
    assert "credits" in result["reason"].lower() or "exhausted" in result["reason"].lower()
    assert "credits" in result["recovery"].lower() or "model" in result["recovery"].lower()


def test_classify_skip_reviewer_quota_exceeded() -> None:
    rv = _skip_reviewer("api_error", "API Error: API_QUOTA_EXCEEDED")
    result = classify_skip_reviewer(rv)
    assert "credits" in result["reason"].lower() or "exhausted" in result["reason"].lower()


def test_classify_skip_reviewer_rate_limit() -> None:
    rv = _skip_reviewer("api_error", "API Error: RATE_LIMIT")
    result = classify_skip_reviewer(rv)
    assert "rate" in result["reason"].lower() or "limit" in result["reason"].lower()
    assert "retry" in result["recovery"].lower() or "concurrency" in result["recovery"].lower()


def test_classify_skip_reviewer_service_unavailable() -> None:
    rv = _skip_reviewer("api_error", "API Error: SERVICE_UNAVAILABLE")
    result = classify_skip_reviewer(rv)
    assert "unavailable" in result["reason"].lower()
    assert "retry" in result["recovery"].lower()


def test_classify_skip_reviewer_parse_failure() -> None:
    rv = _skip_reviewer("parse-failure", "Review output could not be parsed")
    result = classify_skip_reviewer(rv)
    assert "parse" in result["reason"].lower() or "failure" in result["reason"].lower()
    assert "model" in result["recovery"].lower() or "logs" in result["recovery"].lower()


def test_classify_skip_reviewer_parse_failure_empty_findings() -> None:
    """parse-review.py can emit parse-failure SKIPs with empty findings list."""
    rv = {
        "reviewer": "craft",
        "verdict": "SKIP",
        "summary": "review output could not be parsed: no ```json block found",
        "findings": [],
    }
    result = classify_skip_reviewer(rv)
    assert "parse" in result["reason"].lower() or "failure" in result["reason"].lower()
    assert "model" in result["recovery"].lower() or "logs" in result["recovery"].lower()


def test_classify_skip_reviewer_timeout_broad_summary_match() -> None:
    """Timeout without structured finding — detected from 'timeout' keyword in summary."""
    rv = {"reviewer": "flux", "verdict": "SKIP", "summary": "review skipped due to timeout.", "findings": []}
    result = classify_skip_reviewer(rv)
    assert "Timeout" in result["reason"]


def test_format_skip_diagnostics_table_escapes_pipe_in_label() -> None:
    rv = {
        "reviewer": "pipe|reviewer",
        "perspective": "pipe|perspective",
        "verdict": "SKIP",
        "summary": "skipped",
        "findings": [],
    }
    lines = format_skip_diagnostics_table([rv])
    table = "\n".join(lines)
    # The raw pipe in the label must be escaped
    for row in lines:
        if row.startswith("| ") and "Reviewer" not in row and "---" not in row:
            parts = row.split("|")
            # Should have 5 parts: '' | label | reason | recovery | ''
            assert len(parts) == 5, f"Unescaped pipe in row: {row}"


def test_classify_skip_reviewer_network_error_in_summary() -> None:
    rv = {
        "reviewer": "test",
        "verdict": "SKIP",
        "summary": "service unavailable error connecting to provider",
        "findings": [],
    }
    result = classify_skip_reviewer(rv)
    assert "network" in result["reason"].lower() or "unavailable" in result["reason"].lower()


def test_classify_skip_reviewer_unknown_fallback() -> None:
    rv = {"reviewer": "test", "verdict": "SKIP", "summary": "something went wrong", "findings": []}
    result = classify_skip_reviewer(rv)
    assert result["reason"].lower() == "unknown"
    assert result["recovery"]


# ---------------------------------------------------------------------------
# format_skip_diagnostics_table
# ---------------------------------------------------------------------------

def test_format_skip_diagnostics_table_empty() -> None:
    assert format_skip_diagnostics_table([]) == []


def test_format_skip_diagnostics_table_single_timeout() -> None:
    rv = _skip_reviewer("timeout", "Reviewer timeout after 300s", "review skipped due to timeout after 300s.")
    lines = format_skip_diagnostics_table([rv])
    table = "\n".join(lines)
    assert "### Skipped Reviews" in table
    assert "| Reviewer | Reason | Recovery |" in table
    assert "300s" in table
    assert "timeout" in table.lower()


def test_format_skip_diagnostics_table_multiple_reviewers() -> None:
    rvs = [
        _skip_reviewer("timeout", "Timeout", "timeout after 600s."),
        _skip_reviewer("api_error", "API Error: API_CREDITS_DEPLETED"),
        _skip_reviewer("parse-failure", "Review output could not be parsed"),
    ]
    lines = format_skip_diagnostics_table(rvs)
    table = "\n".join(lines)
    # Three data rows plus header/separator
    data_rows = [l for l in lines if l.startswith("| ") and "Reviewer" not in l and "---" not in l]
    assert len(data_rows) == 3


# ---------------------------------------------------------------------------
# Integration: skip diagnostics table in rendered verdict comment
# ---------------------------------------------------------------------------

def _make_skip_reviewer(name: str, category: str, title: str, summary: str = "") -> dict:
    return {
        "reviewer": name,
        "perspective": name.lower(),
        "verdict": "SKIP",
        "confidence": 0.0,
        "summary": summary or f"Skipped: {title}",
        "runtime_seconds": 5,
        "findings": [
            {
                "severity": "info",
                "category": category,
                "file": "",
                "line": 0,
                "title": title,
                "description": "",
                "suggestion": "",
            }
        ],
        "stats": {"critical": 0, "major": 0, "minor": 0, "info": 1},
    }


def test_verdict_comment_includes_skip_diagnostics_table_on_timeout(tmp_path: Path) -> None:
    verdict_data = {
        "verdict": "WARN",
        "summary": "2 reviewers. Failures: 0, warnings: 1, skipped: 1.",
        "reviewers": [
            _make_skip_reviewer("flux", "timeout", "Reviewer timeout after 600s", "review skipped due to timeout after 600s."),
            {
                "reviewer": "trace",
                "perspective": "correctness",
                "verdict": "WARN",
                "confidence": 0.8,
                "summary": "One issue.",
                "runtime_seconds": 90,
                "findings": [],
                "stats": {"critical": 0, "major": 1, "minor": 0, "info": 0},
            },
        ],
        "stats": {"total": 2, "pass": 0, "warn": 1, "fail": 0, "skip": 1},
        "override": {"used": False},
    }

    code, body, err = run_render(tmp_path, verdict_data)

    assert code == 0, err
    assert "### Skipped Reviews" in body
    assert "| Reviewer | Reason | Recovery |" in body
    assert "600s" in body
    assert "timeout" in body.lower()


def test_verdict_comment_includes_skip_diagnostics_table_with_all_types(tmp_path: Path) -> None:
    verdict_data = {
        "verdict": "WARN",
        "summary": "5 reviewers. Failures: 0, warnings: 0, skipped: 5.",
        "reviewers": [
            _make_skip_reviewer("flux", "timeout", "Reviewer timeout after 600s", "review skipped due to timeout after 600s."),
            _make_skip_reviewer("guard", "api_error", "API Error: API_KEY_INVALID"),
            _make_skip_reviewer("atlas", "api_error", "API Error: API_CREDITS_DEPLETED"),
            _make_skip_reviewer("craft", "parse-failure", "Review output could not be parsed"),
            {
                "reviewer": "fuse",
                "perspective": "resilience",
                "verdict": "SKIP",
                "confidence": 0.0,
                "summary": "service unavailable error",
                "runtime_seconds": 2,
                "findings": [],
                "stats": {"critical": 0, "major": 0, "minor": 0, "info": 0},
            },
        ],
        "stats": {"total": 5, "pass": 0, "warn": 0, "fail": 0, "skip": 5},
        "override": {"used": False},
    }

    code, body, err = run_render(tmp_path, verdict_data)

    assert code == 0, err
    assert "### Skipped Reviews" in body
    # At least the 4 structured-finding reviewers should have rows
    data_rows = [
        l for l in body.splitlines()
        if l.startswith("| ") and "Reviewer" not in l and "---" not in l and "Skipped Reviews" not in l
    ]
    assert len(data_rows) >= 4


def test_verdict_comment_no_skip_diagnostics_table_when_no_skips(tmp_path: Path) -> None:
    verdict_data = {
        "verdict": "PASS",
        "summary": "1 reviewer passed.",
        "reviewers": [
            {
                "reviewer": "trace",
                "perspective": "correctness",
                "verdict": "PASS",
                "confidence": 0.95,
                "summary": "All good.",
                "runtime_seconds": 30,
                "findings": [],
                "stats": {"critical": 0, "major": 0, "minor": 0, "info": 0},
            },
        ],
        "stats": {"total": 1, "pass": 1, "warn": 0, "fail": 0, "skip": 0},
        "override": {"used": False},
    }

    code, body, err = run_render(tmp_path, verdict_data)

    assert code == 0, err
    assert "### Skipped Reviews" not in body


def test_detect_skip_banner_parse_failure() -> None:
    rv = {
        "verdict": "SKIP",
        "summary": "no json block",
        "findings": [{"category": "parse-failure", "title": "No JSON", "file": "", "line": 0}],
    }
    banner = detect_skip_banner([rv])
    assert "parse" in banner.lower() or "parsed" in banner.lower()


def test_detect_skip_banner_rate_limit() -> None:
    rv = {
        "verdict": "SKIP",
        "summary": "rate limited",
        "findings": [{"category": "api_error", "title": "API Error: RATE_LIMIT", "file": "", "line": 0}],
    }
    banner = detect_skip_banner([rv])
    assert "rate" in banner.lower() or "limit" in banner.lower()


# ---------------------------------------------------------------------------
# Cross-boundary contract: generate_skip_verdict → classify_skip_reviewer
# Pins the implicit contract between parse-review.py's error_type strings
# and render_verdict_comment.py's classification logic.
# ---------------------------------------------------------------------------

def _load_generate_skip_verdict():
    """Import generate_skip_verdict from parse-review.py via importlib."""
    import importlib.util

    script = ROOT / "scripts" / "parse-review.py"
    spec = importlib.util.spec_from_file_location("parse_review", str(script))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.generate_skip_verdict


@pytest.mark.parametrize("error_type,expected_reason_fragment", [
    ("RATE_LIMIT", "rate"),
    ("API_KEY_INVALID", "auth"),
    ("API_CREDITS_DEPLETED", "credits"),
    ("SERVICE_UNAVAILABLE", "unavailable"),
])
def test_classify_skip_reviewer_contract_with_generate_skip_verdict(
    error_type: str,
    expected_reason_fragment: str,
) -> None:
    """classify_skip_reviewer correctly parses verdicts produced by generate_skip_verdict."""
    generate_skip_verdict = _load_generate_skip_verdict()
    reviewer = generate_skip_verdict(error_type, f"Simulated {error_type} error")
    result = classify_skip_reviewer(reviewer)
    assert expected_reason_fragment in result["reason"].lower(), (
        f"classify_skip_reviewer({error_type!r}) reason={result['reason']!r} "
        f"did not contain {expected_reason_fragment!r}"
    )
