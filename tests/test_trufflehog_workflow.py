from pathlib import Path

import yaml

from lib.consumer_workflow_validator import _WORKFLOW_LOADER

ROOT = Path(__file__).parent.parent


def _load_workflow() -> dict:
    path = ROOT / ".github" / "workflows" / "trufflehog.yml"
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_WORKFLOW_LOADER)


def test_trufflehog_workflow_pins_action_and_uses_event_specific_refs() -> None:
    workflow = _load_workflow()
    step = workflow["jobs"]["trufflehog"]["steps"][1]

    assert step["uses"] == "trufflesecurity/trufflehog@c3e599b7163e8198a55467f3133db0e7b2a492cb"
    assert "github.event.pull_request.base.sha" in step["with"]["base"]
    assert "github.event.before" in step["with"]["base"]
    assert "github.event.pull_request.head.sha" in step["with"]["head"]
    assert "github.sha" in step["with"]["head"]
    assert step["with"]["extra_args"] == "--results=verified,unknown"
