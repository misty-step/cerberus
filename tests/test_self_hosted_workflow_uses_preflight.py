from pathlib import Path

ROOT = Path(__file__).parent.parent
SELF_HOSTED_WORKFLOW = ROOT / ".github" / "workflows" / "cerberus.yml"


def _read_workflow() -> str:
    return SELF_HOSTED_WORKFLOW.read_text()


def test_self_hosted_workflow_uses_preflight_action() -> None:
    content = _read_workflow()

    assert "preflight:" in content
    assert "uses: ./preflight" in content
    assert "should_run" in content
    assert "skip_reason" in content


def test_self_hosted_workflow_wires_api_key() -> None:
    content = _read_workflow()

    assert "api-key:" in content


def test_self_hosted_workflow_removes_draft_check_job() -> None:
    content = _read_workflow()

    assert "draft-check:" not in content
    assert "uses: ./draft-check" not in content
    assert "is_draft" not in content


def test_self_hosted_workflow_removes_bespoke_fork_guard() -> None:
    content = _read_workflow()

    assert "head.repo.full_name == github.repository" not in content


def test_self_hosted_workflow_gates_on_should_run() -> None:
    content = _read_workflow()

    assert "needs.preflight.outputs.should_run == 'true'" in content
    assert "needs.draft-check.outputs.is_draft" not in content
