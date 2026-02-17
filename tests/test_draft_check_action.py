from pathlib import Path

ROOT = Path(__file__).parent.parent
DRAFT_CHECK_ACTION_FILE = ROOT / "draft-check" / "action.yml"


def test_draft_check_action_exists_and_upserts_comment() -> None:
    content = DRAFT_CHECK_ACTION_FILE.read_text()

    assert 'name: "Cerberus Draft Check"' in content
    assert "<!-- cerberus:draft-check -->" in content
    assert "scripts/lib/github.py" in content
    assert "outputs:" in content
    assert "is_draft:" in content

