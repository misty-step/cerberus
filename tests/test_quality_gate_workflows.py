from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent


def _workflow_loader() -> type[yaml.SafeLoader]:
    class Loader(yaml.SafeLoader):
        pass

    for ch in "OoYyNn":
        resolvers = Loader.yaml_implicit_resolvers.get(ch)
        if not resolvers:
            continue
        Loader.yaml_implicit_resolvers[ch] = [
            (tag, regexp)
            for (tag, regexp) in resolvers
            if tag != "tag:yaml.org,2002:bool"
        ]
    return Loader


def _load_workflow(relative_path: str) -> dict:
    path = ROOT / relative_path
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_workflow_loader())


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
