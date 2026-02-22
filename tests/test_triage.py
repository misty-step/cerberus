"""Unit tests for triage runtime behavior."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


def load_triage_module():
    # `scripts/triage.py` is an executable script (not package module), so load directly.
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
## ❌ Cerberus Verdict: FAIL
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
        {"user": {"login": "github-actions[bot]"}, "body": "<!-- cerberus:triage sha=abc1234 run=1 -->"},
        {"user": {"login": "github-actions[bot]"}, "body": "<!-- cerberus:triage sha=abc1234 run=2 -->"},
        {"user": {"login": "github-actions[bot]"}, "body": "<!-- cerberus:triage sha=def5678 run=3 -->"},
        {"user": {"login": "github-actions[bot]"}, "body": "plain comment"},
    ]
    assert triage.count_attempts_for_sha(comments, "abc1234deadbeef", "github-actions[bot]") == 2
    assert triage.count_attempts_for_sha(comments, "def5678cafebabe", "github-actions[bot]") == 1
    assert triage.count_attempts_for_sha(comments, "0000000", "github-actions[bot]") == 0


def test_count_attempts_ignores_untrusted_comments() -> None:
    triage = load_triage_module()

    comments = [
        {"user": {"login": "external-user"}, "body": "<!-- cerberus:triage sha=abc1234 run=1 -->"},
        {"user": {"login": "github-actions[bot]"}, "body": "<!-- cerberus:triage sha=abc1234 run=2 -->"},
    ]
    assert triage.count_attempts_for_sha(comments, "abc1234deadbeef", "github-actions[bot]") == 1


def test_latest_council_comment_ignores_untrusted_spoof() -> None:
    triage = load_triage_module()

    comments = [
        {
            "user": {"login": "external-user"},
            "updated_at": "2026-02-08T02:00:00Z",
            "body": "<!-- cerberus:council -->\n## ❌ Cerberus Verdict: FAIL",
        },
        {
            "user": {"login": "github-actions[bot]"},
            "updated_at": "2026-02-08T01:00:00Z",
            "body": "<!-- cerberus:council -->\n## ✅ Cerberus Verdict: PASS",
        },
    ]
    latest = triage.find_latest_council_comment(comments, "github-actions[bot]")
    assert latest is not None
    assert triage.extract_council_verdict(latest["body"]) == "PASS"


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


def test_run_fix_command_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    triage = load_triage_module()

    def fake_subprocess_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(triage.subprocess, "run", fake_subprocess_run)

    outcome, details = triage.run_fix_command("make nope")
    assert outcome == "fix_failed"
    assert "boom" in details


def test_run_fix_command_reports_no_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    triage = load_triage_module()

    def fake_subprocess_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")

    def fake_run(argv, **kwargs):
        assert argv == ["git", "status", "--porcelain"]
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(triage.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(triage, "run", fake_run)

    outcome, details = triage.run_fix_command("echo hi")
    assert outcome == "no_changes"
    assert "no file changes" in details.lower()


def test_run_fix_command_commits_when_changes_present(monkeypatch: pytest.MonkeyPatch) -> None:
    triage = load_triage_module()
    seen = []

    def fake_subprocess_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")

    def fake_run(argv, **kwargs):
        seen.append(tuple(argv))
        if argv == ["git", "status", "--porcelain"]:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout="M file.py\n", stderr="")
        if argv == ["git", "rev-parse", "--short", "HEAD"]:
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout="abc123\n", stderr="")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(triage.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(triage, "run", fake_run)

    outcome, details = triage.run_fix_command("echo hi")
    assert outcome == "fixed"
    assert "abc123" in details
    assert ("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com") in seen
    assert ("git", "config", "user.name", "github-actions[bot]") in seen
    assert ("git", "add", "-A") in seen
    assert ("git", "commit", "-m", "[triage] auto-fix from Cerberus") in seen


def test_triage_pr_skips_when_verdict_not_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    triage = load_triage_module()

    pull_payload = {
        "head": {
            "sha": "abc123456789",
            "ref": "feature/branch",
            "repo": {"full_name": "misty-step/cerberus"},
        }
    }
    comments_payload = [
        {
            "user": {"login": "github-actions[bot]"},
            "updated_at": "2026-02-08T01:00:00Z",
            "body": "<!-- cerberus:council -->\n## ✅ Cerberus Verdict: PASS",
        }
    ]
    commit_payload = {"commit": {"message": "normal commit"}}

    def fake_gh_json(args):
        endpoint = args[0]
        if endpoint.endswith("/pulls/60"):
            return pull_payload
        if endpoint.endswith("/issues/60/comments?per_page=100"):
            return comments_payload
        if endpoint.endswith("/commits/abc123456789"):
            return commit_payload
        raise AssertionError(endpoint)

    def fail_if_called(**kwargs):
        raise AssertionError("post_triage_comment should not run for skipped verdicts")

    monkeypatch.setattr(triage, "gh_json", fake_gh_json)
    monkeypatch.setattr(triage, "post_triage_comment", fail_if_called)

    result = triage.triage_pr(
        repo="misty-step/cerberus",
        pr_number=60,
        mode="diagnose",
        trigger="automatic",
        max_attempts=1,
        stale_hours=24,
        run_id="1",
        now=datetime(2026, 2, 8, 3, 0, tzinfo=UTC),
    )
    assert result.status == "skipped"
    assert result.reason == "pr_60_verdict_pass"
    assert result.attempted is False


def test_triage_pr_diagnose_posts_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    triage = load_triage_module()
    posted = {}

    pull_payload = {
        "head": {
            "sha": "abc123456789",
            "ref": "feature/branch",
            "repo": {"full_name": "misty-step/cerberus"},
        }
    }
    comments_payload = [
        {
            "user": {"login": "github-actions[bot]"},
            "updated_at": "2026-02-08T01:00:00Z",
            "body": "<!-- cerberus:council -->\n## ❌ Cerberus Verdict: FAIL\ncouncil details",
        }
    ]
    commit_payload = {"commit": {"message": "normal commit"}}

    def fake_gh_json(args):
        endpoint = args[0]
        if endpoint.endswith("/pulls/60"):
            return pull_payload
        if endpoint.endswith("/issues/60/comments?per_page=100"):
            return comments_payload
        if endpoint.endswith("/commits/abc123456789"):
            return commit_payload
        raise AssertionError(endpoint)

    def fake_post(**kwargs):
        posted.update(kwargs)

    monkeypatch.setattr(triage, "gh_json", fake_gh_json)
    monkeypatch.setattr(triage, "post_triage_comment", fake_post)

    result = triage.triage_pr(
        repo="misty-step/cerberus",
        pr_number=60,
        mode="diagnose",
        trigger="automatic",
        max_attempts=1,
        stale_hours=24,
        run_id="1",
        now=datetime(2026, 2, 8, 3, 0, tzinfo=UTC),
    )
    assert result.status == "diagnosed"
    assert result.attempted is True
    assert posted["outcome"] == "diagnosed"
    assert posted["verdict"] == "FAIL"


def test_triage_pr_fix_push_failure_reports_fix_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    triage = load_triage_module()
    posted = {}

    pull_payload = {
        "head": {
            "sha": "abc123456789",
            "ref": "feature/branch",
            "repo": {"full_name": "misty-step/cerberus"},
        }
    }
    comments_payload = [
        {
            "user": {"login": "github-actions[bot]"},
            "updated_at": "2026-02-08T01:00:00Z",
            "body": "<!-- cerberus:council -->\n## ❌ Cerberus Verdict: FAIL",
        }
    ]
    commit_payload = {"commit": {"message": "normal commit"}}

    def fake_gh_json(args):
        endpoint = args[0]
        if endpoint.endswith("/pulls/60"):
            return pull_payload
        if endpoint.endswith("/issues/60/comments?per_page=100"):
            return comments_payload
        if endpoint.endswith("/commits/abc123456789"):
            return commit_payload
        raise AssertionError(endpoint)

    def fake_post(**kwargs):
        posted.update(kwargs)

    def fake_fix(command):
        return "fixed", "commit made"

    def fake_subprocess_run(argv, **kwargs):
        assert argv[:3] == ["git", "push", "origin"]
        return subprocess.CompletedProcess(args=argv, returncode=1, stdout="", stderr="network fail")

    monkeypatch.setattr(triage, "gh_json", fake_gh_json)
    monkeypatch.setattr(triage, "post_triage_comment", fake_post)
    monkeypatch.setattr(triage, "run_fix_command", fake_fix)
    monkeypatch.setattr(triage.Path, "exists", lambda self: True)
    monkeypatch.setattr(triage.subprocess, "run", fake_subprocess_run)

    result = triage.triage_pr(
        repo="misty-step/cerberus",
        pr_number=60,
        mode="fix",
        trigger="automatic",
        max_attempts=1,
        stale_hours=24,
        run_id="1",
        now=datetime(2026, 2, 8, 3, 0, tzinfo=UTC),
    )
    assert result.status == "fix_failed"
    assert result.attempted is True
    assert posted["outcome"] == "fix_failed"
    assert "push failed" in posted["details"].lower()


# ---------------------------------------------------------------------------
# gather_diagnosis
# ---------------------------------------------------------------------------


class TestGatherDiagnosis:
    """Tests for gather_diagnosis covering branding-changed lines."""

    def test_none_body(self) -> None:
        triage = load_triage_module()
        result = triage.gather_diagnosis(None)
        assert "not found" in result

    def test_empty_body(self) -> None:
        triage = load_triage_module()
        result = triage.gather_diagnosis("")
        assert "not found" in result

    def test_only_headers_and_footer(self) -> None:
        triage = load_triage_module()
        body = "## Verdict\n---\n*Cerberus (v2) | 3 findings*\n"
        result = triage.gather_diagnosis(body)
        assert "empty" in result

    def test_extracts_findings(self) -> None:
        triage = load_triage_module()
        body = "## Verdict\nSome finding here\nAnother finding\n"
        result = triage.gather_diagnosis(body)
        assert "Some finding here" in result
        assert "Another finding" in result
