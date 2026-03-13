"""Doc contract checks for reviewer benchmark planning surfaces."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).parent.parent
BENCHMARK_DIR = ROOT / "docs" / "reviewer-benchmark"
BENCHMARK_README = BENCHMARK_DIR / "README.md"
BACKLOG = ROOT / "docs" / "BACKLOG-PRIORITIES.md"


def test_benchmark_readme_latest_report_exists() -> None:
    readme = BENCHMARK_README.read_text(encoding="utf-8")
    match = re.search(r"- `(\d{4}-\d{2}-\d{2}-org-scorecard\.md)`", readme)
    assert match is not None, "README must point to the latest dated scorecard"

    latest_report = BENCHMARK_DIR / match.group(1)
    assert latest_report.exists(), f"Latest scorecard missing: {latest_report.name}"


def test_backlog_tracks_current_benchmark_workstreams() -> None:
    backlog = BACKLOG.read_text(encoding="utf-8")

    expected_sections = [
        "`P0` Security/dataflow blind-spot hardening",
        "Tracking: `#333`",
        "`P0` Large-PR review reliability",
        "Tracking: `#334`",
        "`P1` Lifecycle/state-machine challenger lane",
        "Tracking: `#335`",
        "`P1` Adjacent-regression detection",
        "Tracking: `#336`",
        "`P1` Benchmark loop",
        "Tracking: `#332`",
        "`P1` Reviewer presence / self-dogfood coverage",
    ]

    for expected in expected_sections:
        assert expected in backlog
