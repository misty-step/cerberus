import json
import os
import subprocess
import sys
from pathlib import Path

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
    assert "**Summary:** 1/2 reviewers passed. 1 failed (VULCAN)." in body
    assert "**Review Scope:** 7 files changed, +120 / -44 lines" in body
    assert "### Reviewer Overview" in body
    assert "VULCAN" in body
    assert "runtime `1m 5s`" in body
    assert "Reviewer details (click to expand)" in body
    assert "blob/abcdef1234567890/src/service.py#L42" in body
    assert "/council override sha=abcdef123456" in body


def test_renders_skip_banner_for_credit_exhaustion(tmp_path: Path) -> None:
    council = {
        "verdict": "WARN",
        "summary": "2 reviewers. Failures: 0, warnings: 1, skipped: 1.",
        "reviewers": [
            {
                "reviewer": "SENTINEL",
                "perspective": "security",
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
    assert "**Summary:** 0/2 reviewers passed. 1 warned (ATHENA). 1 skipped (SENTINEL)." in body
    assert "[#12345](https://github.com/misty-step/cerberus/actions/runs/12345)" in body


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
                    "findings": [],
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
