from pathlib import Path

ROOT = Path(__file__).parent.parent
CONSUMER_WORKFLOW_FILE = ROOT / "templates" / "consumer-workflow.yml"


def test_consumer_workflow_uses_preflight_action() -> None:
    content = CONSUMER_WORKFLOW_FILE.read_text()

    assert "preflight:" in content
    assert "misty-step/cerberus/preflight@v2" in content
    assert "should_run" in content
    assert "skip_reason" in content


def test_consumer_workflow_removes_bespoke_fork_and_draft_skip_logic() -> None:
    content = CONSUMER_WORKFLOW_FILE.read_text()

    assert "draft-check:" not in content
    assert "is_fork:" not in content
    assert "head.repo.full_name == github.repository" not in content
    assert "needs.preflight.outputs.should_run == 'true'" in content
    assert "needs.draft-check.outputs.is_draft" not in content
    assert "needs.triage.outputs.is_fork" not in content
