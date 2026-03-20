"""Doc contract checks for reviewer benchmark planning surfaces."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).parent.parent
BENCHMARK_DIR = ROOT / "docs" / "reviewer-benchmark"
BENCHMARK_README = BENCHMARK_DIR / "README.md"
BACKLOG = ROOT / "docs" / "BACKLOG-PRIORITIES.md"


def _assert_local_artifact_refs_exist(section: str, line: str) -> None:
    for ref in re.findall(r"`([^`]+)`", line):
        if "/" not in ref:
            continue
        if re.match(r"^[A-Za-z0-9_.-]+#\d+$", ref):
            continue
        assert (ROOT / ref).exists(), f"{section} references missing artifact: {ref}"


def test_benchmark_readme_latest_report_exists() -> None:
    readme = BENCHMARK_README.read_text(encoding="utf-8")
    match = re.search(
        r"^Latest report:\s*\n- `(\d{4}-\d{2}-\d{2}-org-scorecard\.md)`",
        readme,
        re.MULTILINE,
    )
    assert match is not None, "README must point to the latest dated scorecard under 'Latest report:'"

    latest_report_name = match.group(1)
    latest_report = BENCHMARK_DIR / latest_report_name
    assert latest_report.exists(), f"Latest scorecard missing: {latest_report.name}"

    newest_scorecard = max(path.name for path in BENCHMARK_DIR.glob("*-org-scorecard.md"))
    assert latest_report_name == newest_scorecard, (
        f"README latest report should point to newest scorecard: {newest_scorecard}"
    )


def test_backlog_tracks_current_benchmark_workstreams() -> None:
    backlog = BACKLOG.read_text(encoding="utf-8")
    expected_workstreams = {
        "`P0` Security/dataflow blind-spot hardening": "#333",
        "`P0` Large-PR timeout/blind-spot reduction": "#334",
        "`P1` Benchmark loop": "#332",
        "`P1` Lifecycle/state-machine challenger reasoning": "#335",
        "`P1` Adjacent-regression detection for workflow/infra changes": "#336",
        "`P1` Reviewer presence / self-dogfood coverage monitoring": "#375",
        "`P1` Typed repo/GitHub context access for agentic review": "#57",
        "`P1` Prompt-contract simplification for tool-driven review": "#381",
        "`P1` Eval coverage for tool selection, grounding, and prompt-injection resistance": "#380",
    }

    section_pattern = re.compile(
        r"^- (?P<section>`P\d` [^\n]+)\n(?P<body>(?:  - [^\n]+\n)+)",
        re.MULTILINE,
    )
    tracked_workstreams = {}
    for match in section_pattern.finditer(backlog):
        body = match.group("body")
        tracking = re.search(r"^  - Tracking: `(?P<issue>#\d+)`$", match.group("body"), re.MULTILINE)
        if tracking is not None:
            benchmark_match = re.search(r"^  - Benchmark evidence: .+$", body, re.MULTILINE)
            assert benchmark_match, (
                f"{match.group('section')} must declare benchmark evidence"
            )
            verification_match = re.search(r"^  - Verification: .+$", body, re.MULTILINE)
            assert verification_match, (
                f"{match.group('section')} must declare verification"
            )
            _assert_local_artifact_refs_exist(match.group("section"), benchmark_match.group(0))
            _assert_local_artifact_refs_exist(match.group("section"), verification_match.group(0))
            tracked_workstreams[match.group("section")] = tracking.group("issue")

    assert tracked_workstreams == expected_workstreams
