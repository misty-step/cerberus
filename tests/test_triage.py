"""Unit tests for triage runtime behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def load_triage_module():
    script = Path(__file__).parent.parent / "scripts" / "triage.py"
    spec = spec_from_file_location("triage", script)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extract_council_verdict() -> None:
    triage = load_triage_module()

    body = """<!-- cerberus:council -->
## ❌ Council Verdict: FAIL
Details
"""
    assert triage.extract_council_verdict(body) == "FAIL"


def test_extract_council_verdict_missing() -> None:
    triage = load_triage_module()

    assert triage.extract_council_verdict("No verdict here") is None


def test_parse_triage_command_mode_default() -> None:
    triage = load_triage_module()

    assert triage.parse_triage_command_mode("/cerberus triage", "diagnose") == "diagnose"


def test_parse_triage_command_mode_override() -> None:
    triage = load_triage_module()

    assert triage.parse_triage_command_mode("/cerberus triage mode=fix", "diagnose") == "fix"


def test_parse_triage_command_mode_invalid_falls_back() -> None:
    triage = load_triage_module()

    assert triage.parse_triage_command_mode("/cerberus triage mode=explode", "diagnose") == "diagnose"


def test_has_triage_commit_tag() -> None:
    triage = load_triage_module()

    assert triage.has_triage_commit_tag("[triage] fix lint errors")
    assert not triage.has_triage_commit_tag("fix lint errors")


def test_count_attempts_for_sha() -> None:
    triage = load_triage_module()

    comments = [
        {"body": "<!-- cerberus:triage sha=abc1234 run=1 -->"},
        {"body": "<!-- cerberus:triage sha=abc1234 run=2 -->"},
        {"body": "<!-- cerberus:triage sha=def5678 run=3 -->"},
        {"body": "plain comment"},
    ]
    assert triage.count_attempts_for_sha(comments, "abc1234deadbeef") == 2
    assert triage.count_attempts_for_sha(comments, "def5678cafebabe") == 1
    assert triage.count_attempts_for_sha(comments, "0000000") == 0


def test_schedule_selector_requires_stale_fail_and_attempt_room() -> None:
    triage = load_triage_module()

    now = datetime(2026, 2, 8, 3, 0, tzinfo=UTC)
    stale_fail_at = "2026-02-07T00:00:00Z"
    fresh_fail_at = "2026-02-08T02:30:00Z"
    old_pass_at = "2026-02-07T00:00:00Z"

    assert triage.should_schedule_pr(
        verdict="FAIL",
        council_updated_at=stale_fail_at,
        attempts_for_sha=0,
        max_attempts=1,
        stale_hours=24,
        now=now,
    )
    assert not triage.should_schedule_pr(
        verdict="FAIL",
        council_updated_at=fresh_fail_at,
        attempts_for_sha=0,
        max_attempts=1,
        stale_hours=24,
        now=now,
    )
    assert not triage.should_schedule_pr(
        verdict="PASS",
        council_updated_at=old_pass_at,
        attempts_for_sha=0,
        max_attempts=1,
        stale_hours=24,
        now=now,
    )
    assert not triage.should_schedule_pr(
        verdict="FAIL",
        council_updated_at=stale_fail_at,
        attempts_for_sha=1,
        max_attempts=1,
        stale_hours=24,
        now=now,
    )
