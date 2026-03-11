"""Regression tests for infra review guidance added in issue #295."""

from pathlib import Path


ROOT = Path(__file__).parent.parent
CORRECTNESS_AGENT = ROOT / ".opencode" / "agents" / "correctness.md"
SECURITY_AGENT = ROOT / ".opencode" / "agents" / "security.md"
PARSE_REVIEW = ROOT / "scripts" / "parse-review.py"


def test_correctness_agent_includes_infra_cross_check_guidance() -> None:
    text = CORRECTNESS_AGENT.read_text(encoding="utf-8")

    assert "Infrastructure Configuration Cross-Check" in text
    assert (
        "When the diff touches `.dockerignore`, `Dockerfile`, `docker-compose.yml`, "
        "`fly.toml`, or similar deployment/config files:"
    ) in text
    assert "startup file reads" in text
    assert "Cross-file startup breakage is in scope" in text
    assert "inconsistent PEM header formats" in text
    assert "Do NOT use `[unverified]` for static observations" in text


def test_security_agent_includes_dockerignore_and_non_root_guidance() -> None:
    text = SECURITY_AGENT.read_text(encoding="utf-8")

    assert "Infrastructure Threat Model" in text
    assert "Infrastructure-only PRs are not lower risk" in text
    assert (
        "When the diff touches `Dockerfile`, `.dockerignore`, `docker-compose.yml`, "
        "`fly.toml`, container/build config, or secret-loading config:"
    ) in text
    assert ".env" in text
    assert ".env.*" in text
    assert "*.sqlite" in text
    assert "*.db" in text
    assert "data/" in text
    assert "non-root `USER` directive" in text
    assert "Do NOT mark directly-readable static findings as `[unverified]`" in text


def test_parse_review_documents_unverified_scope_boundary() -> None:
    text = PARSE_REVIEW.read_text(encoding="utf-8")

    assert "suggestion_verified / [unverified] is guidance for behavioral uncertainty" in text
    assert "missing Dockerfile directives" in text
    assert "`.dockerignore` exclusions" in text
