from pathlib import Path

import yaml

from lib.consumer_workflow_validator import _WORKFLOW_LOADER

ROOT = Path(__file__).parent.parent


def _load_workflow(relative_path: str) -> dict:
    path = ROOT / relative_path
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_WORKFLOW_LOADER)


def test_ci_workflow_uses_explicit_merge_gate_job() -> None:
    workflow = _load_workflow(".github/workflows/ci.yml")

    assert workflow["name"] == "Quality Checks"
    assert "merge-gate" in workflow["jobs"]
    assert workflow["jobs"]["merge-gate"]["name"] == "merge-gate"


def test_sync_tag_workflows_follow_quality_checks_workflow_name() -> None:
    sync_v1 = _load_workflow(".github/workflows/sync-v1-tag.yml")
    sync_v2 = _load_workflow(".github/workflows/sync-v2-tag.yml")

    assert sync_v1["on"]["workflow_run"]["workflows"] == ["Quality Checks"]
    assert sync_v2["on"]["workflow_run"]["workflows"] == ["Quality Checks"]
