from pathlib import Path

ROOT = Path(__file__).parent.parent
CONSUMER_WORKFLOW_FILE = ROOT / "templates" / "consumer-workflow.yml"


def test_consumer_workflow_uses_reusable_workflow() -> None:
    """consumer-workflow.yml delegates to the Cerberus reusable workflow."""
    content = CONSUMER_WORKFLOW_FILE.read_text()

    assert "uses: misty-step/cerberus/.github/workflows/cerberus.yml@v2" in content
    assert "api-key:" in content


def test_consumer_workflow_has_no_bespoke_skip_logic() -> None:
    """Skip logic is handled internally by the reusable workflow."""
    content = CONSUMER_WORKFLOW_FILE.read_text()

    assert "draft-check:" not in content
    assert "is_fork:" not in content
    assert "head.repo.full_name == github.repository" not in content
    assert "needs.draft-check.outputs.is_draft" not in content
    assert "needs.triage.outputs.is_fork" not in content
