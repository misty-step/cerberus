from pathlib import Path

ROOT = Path(__file__).parent.parent
TRIAGE_ACTION_FILE = ROOT / "triage" / "action.yml"
TRIAGE_WORKFLOW_TEMPLATE = ROOT / "templates" / "triage-workflow.yml"


def test_triage_action_exists_and_calls_runtime_script() -> None:
    content = TRIAGE_ACTION_FILE.read_text()

    assert "name: 'Cerberus Triage'" in content
    assert "scripts/triage.py" in content
    assert "mode:" in content
    assert "default: 'off'" in content


def test_triage_template_supports_all_triggers() -> None:
    content = TRIAGE_WORKFLOW_TEMPLATE.read_text()

    assert "issue_comment:" in content
    assert "schedule:" in content
    assert "pull_request:" in content
    assert "triage-auto:" in content
    assert "triage-manual:" in content
    assert "triage-scheduled:" in content
    assert "misty-step/cerberus/triage@v1" in content
