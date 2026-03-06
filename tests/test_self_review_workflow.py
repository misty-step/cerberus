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


def test_self_review_workflow_is_opt_in_via_label() -> None:
    workflow = yaml.load(
        (ROOT / ".github/workflows/self-review.yml").read_text(encoding="utf-8"),
        Loader=_workflow_loader(),
    )

    assert workflow["on"]["pull_request"]["types"] == ["labeled"]
    assert workflow["jobs"]["review"]["if"] == "github.event.label.name == 'cerberus-review'"
