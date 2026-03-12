"""Regression tests for infra review guidance added in issues #295 and #302."""

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
    assert "If you cannot quote exact code, omit the finding." in text


def test_security_agent_includes_infra_and_workflow_supply_chain_guidance() -> None:
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
    assert "omit the finding instead of inventing a weaker fallback label" in text
    assert "GitHub Actions Supply-Chain" in text
    assert "When the diff touches `.github/workflows/*.yml`, `.github/workflows/*.yaml`" in text
    assert "Treat `uses: owner/repo@<ref>` as a supply-chain check" in text
    assert "mutable branch ref (`@master`, `@main`, `@develop`, or similar)" in text
    assert "partial semver tag that is not a full three-part release" in text
    assert "`@v1`, `@v2`, or `@v1.2`" in text
    assert "report at least `minor`" in text
    assert "Escalate to `major`" in text
    assert "including via sibling `env:` or `with:` keys on the action step" in text
    assert "or via a `secrets:` block on a reusable-workflow `uses:` call" in text
    assert "AWS_ACCESS_KEY_ID" in text
    assert "GITHUB_TOKEN" in text
    assert "Acceptable third-party refs are full pinned SHAs" in text
    assert "full release tags such as `@v1.2.3`" in text
    assert "semver-style tags such as `actions/checkout@v4`" in text
    assert "actions/*` or `github/*` actions on mutable branch refs" in text
    assert "trusted-provider refs by policy" in text
    assert "Prefer concrete fixes: pin the action to a full commit SHA" in text


def test_parse_review_documents_findings_as_first_class_items() -> None:
    text = PARSE_REVIEW.read_text(encoding="utf-8")

    assert "Findings are first-class review items." in text
    assert "should not invent a second" in text
    assert '"verified vs unverified finding" state' in text
