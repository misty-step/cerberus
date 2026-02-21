from pathlib import Path

ROOT = Path(__file__).parent.parent
SELF_HOSTED_WORKFLOW = ROOT / ".github" / "workflows" / "cerberus.yml"


def test_self_hosted_workflow_uses_preflight_action() -> None:
    content = SELF_HOSTED_WORKFLOW.read_text()

    assert "preflight:" in content
    assert "uses: ./preflight" in content
    assert "should_run" in content


def test_self_hosted_workflow_removes_draft_check_job() -> None:
    content = SELF_HOSTED_WORKFLOW.read_text()

    assert "draft-check:" not in content
    assert "uses: ./draft-check" not in content
    assert "is_draft" not in content


def test_self_hosted_workflow_gates_on_should_run() -> None:
    content = SELF_HOSTED_WORKFLOW.read_text()

    assert "needs.preflight.outputs.should_run == 'true'" in content
    assert "needs.draft-check.outputs.is_draft" not in content
