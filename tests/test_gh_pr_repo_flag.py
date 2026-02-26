"""Regression tests: gh PR commands must pass --repo when checkout is absent."""

from pathlib import Path

ROOT = Path(__file__).parent.parent
REUSABLE_WORKFLOW = ROOT / ".github" / "workflows" / "cerberus.yml"
SELF_REVIEW_WORKFLOW = ROOT / ".github" / "workflows" / "self-review.yml"
MINIMAL_TEMPLATE = ROOT / "templates" / "consumer-workflow-minimal.yml"


def test_reusable_workflow_route_fetches_diff_with_repo_flag() -> None:
    content = REUSABLE_WORKFLOW.read_text()
    assert 'REPO: ${{ github.repository }}' in content, (
        "Reusable workflow route job must define REPO env var"
    )
    assert 'gh pr diff ${{ github.event.pull_request.number }} --repo "$REPO"' in content, (
        "Reusable workflow route job must pass --repo to gh pr diff"
    )


def test_self_review_workflow_delegates_to_reusable_workflow() -> None:
    content = SELF_REVIEW_WORKFLOW.read_text()
    assert "uses: ./.github/workflows/cerberus.yml" in content, (
        "Self-review workflow should delegate to the reusable Cerberus workflow"
    )


def test_decomposed_template_fetches_diff_with_repo_flag() -> None:
    content = MINIMAL_TEMPLATE.read_text()
    assert 'REPO: ${{ github.repository }}' in content, (
        "Decomposed consumer template route job must define REPO env var"
    )
    assert 'gh pr diff ${{ github.event.pull_request.number }} --repo "$REPO"' in content, (
        "Decomposed consumer template should pass --repo to gh pr diff for robustness"
    )
