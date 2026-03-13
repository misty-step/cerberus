from pathlib import Path


ROOT = Path(__file__).parent.parent
SECURITY_AGENT = ROOT / ".opencode" / "agents" / "security.md"
SECURITY_SKILL = ROOT / "pi" / "skills" / "security-review" / "SKILL.md"


def test_security_agent_has_indirect_reentry_section() -> None:
    text = SECURITY_AGENT.read_text(encoding="utf-8")

    assert "Indirect Untrusted-Data Re-entry" in text
    assert "titles and branch names" in text
    assert "fail-open defaults" in text
    assert "raw error leakage" in text
    assert "async side-effect failure paths" in text
    assert "serialization and public-route exposure" in text


def test_security_agent_requires_attack_path_for_metadata_and_defaults() -> None:
    text = SECURITY_AGENT.read_text(encoding="utf-8")

    assert "trusted-looking metadata" in text
    assert "input → sink → impact" in text
    assert "default posture" in text


def test_security_skill_mirrors_indirect_reentry_checklist() -> None:
    text = SECURITY_SKILL.read_text(encoding="utf-8")

    assert "trusted-looking metadata" in text
    assert "titles and branch names" in text
    assert "fail-open defaults" in text
    assert "raw error leakage" in text
    assert "async side-effect failures" in text
    assert "serialization and public-route exposure" in text
