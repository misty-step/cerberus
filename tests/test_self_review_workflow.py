from pathlib import Path

import yaml

from lib.consumer_workflow_validator import _WORKFLOW_LOADER

ROOT = Path(__file__).parent.parent


def test_self_review_workflow_is_opt_in_via_label() -> None:
    workflow = yaml.load(
        (ROOT / ".github/workflows/self-review.yml").read_text(encoding="utf-8"),
        Loader=_WORKFLOW_LOADER,
    )

    assert workflow["on"]["pull_request"]["types"] == ["labeled"]
    assert workflow["jobs"]["review"]["if"] == "github.event.label.name == 'cerberus-review'"
