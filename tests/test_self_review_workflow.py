from pathlib import Path

import yaml

from lib.consumer_workflow_validator import _WORKFLOW_LOADER

ROOT = Path(__file__).parent.parent


def test_self_review_workflow_runs_on_normal_pr_activity() -> None:
    workflow = yaml.load(
        (ROOT / ".github/workflows/self-review.yml").read_text(encoding="utf-8"),
        Loader=_WORKFLOW_LOADER,
    )

    assert workflow["on"]["pull_request"]["types"] == [
        "opened",
        "synchronize",
        "reopened",
        "ready_for_review",
        "converted_to_draft",
    ]
    assert "if" not in workflow["jobs"]["review"]
