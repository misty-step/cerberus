import pytest
from pathlib import Path


ROOT = Path(__file__).parent.parent
SECURITY_AGENT = ROOT / ".opencode" / "agents" / "security.md"
SECURITY_SKILL = ROOT / "pi" / "skills" / "security-review" / "SKILL.md"


@pytest.fixture(scope="module")
def security_prompt_texts() -> tuple[str, str]:
    return (
        SECURITY_AGENT.read_text(encoding="utf-8"),
        SECURITY_SKILL.read_text(encoding="utf-8"),
    )


def test_security_agent_has_indirect_reentry_section(security_prompt_texts: tuple[str, str]) -> None:
    text, _ = security_prompt_texts

    assert "Indirect Untrusted-Data Re-entry" in text
    assert "titles and branch names" in text
    assert "fail-open defaults" in text
    assert "raw error leakage" in text
    assert "async side-effect failure paths" in text
    assert "serialization and public-route exposure" in text


def test_security_agent_requires_attack_path_for_metadata_and_defaults(
    security_prompt_texts: tuple[str, str]
) -> None:
    text, _ = security_prompt_texts

    assert "trusted-looking metadata" in text
    assert "Reasoning pass for these cases" in text
    assert "input → sink → impact" in text
    assert "default posture" in text


def test_security_skill_mirrors_indirect_reentry_checklist(security_prompt_texts: tuple[str, str]) -> None:
    _, text = security_prompt_texts

    assert "trusted-looking metadata" in text
    assert "titles and branch names" in text
    assert "fail-open defaults" in text
    assert "raw error leakage" in text
    assert "async side-effect failures" in text
    assert "serialization and public-route exposure" in text
