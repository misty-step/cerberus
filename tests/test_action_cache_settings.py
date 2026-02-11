"""Regression test for #110: setup-node cache must be disabled.

actions/setup-node@v5 defaults package-manager-cache to true, which
auto-detects the consumer repo's package manager (pnpm, yarn, etc.) and
tries to cache its store.  Since cerberus only does `npm i -g`, no store
directory exists and the post-run save fails — marking PASS jobs as failed.
"""

import re
from pathlib import Path

import yaml

ACTION_YML = Path(__file__).parent.parent / "action.yml"


def _load_action():
    return yaml.safe_load(ACTION_YML.read_text())


def _find_step(steps, name_pattern):
    for step in steps:
        if re.search(name_pattern, step.get("name", ""), re.IGNORECASE):
            return step
    return None


def test_setup_node_disables_package_manager_cache():
    action = _load_action()
    steps = action["runs"]["steps"]
    node_step = _find_step(steps, r"setup node|node\.js")
    assert node_step is not None, "setup-node step not found in action.yml"

    with_block = node_step.get("with", {})
    assert with_block.get("package-manager-cache") is False, (
        "setup-node must set package-manager-cache: false to prevent "
        "post-run cache failures when consumer repos use pnpm/yarn (#110)"
    )


def test_setup_python_does_not_enable_cache():
    action = _load_action()
    steps = action["runs"]["steps"]
    python_step = _find_step(steps, r"setup python|python")
    assert python_step is not None, "setup-python step not found in action.yml"

    with_block = python_step.get("with", {})
    assert "cache" not in with_block or with_block["cache"] in (None, "", False), (
        "setup-python should not enable pip caching — cerberus has no "
        "pip dependencies to cache"
    )
