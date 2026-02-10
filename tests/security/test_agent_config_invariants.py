"""Verify all agent configs enforce security invariants.

Every reviewer agent MUST deny bash and edit access at both the tool
and permission layers.  Write access must be restricted to /tmp/*.
"""

import re
from pathlib import Path

import pytest
import yaml

AGENTS_DIR = Path(__file__).parent.parent.parent / ".opencode" / "agents"
AGENT_FILES = sorted(AGENTS_DIR.glob("*.md"))

# Sanity: ensure we actually found agent files.
assert len(AGENT_FILES) >= 5, f"Expected >=5 agent configs, found {len(AGENT_FILES)}"


def _parse_frontmatter(path: Path) -> dict:
    text = path.read_text()
    match = re.match(r"^---\n(.+?)\n---", text, re.DOTALL)
    assert match, f"No YAML frontmatter in {path.name}"
    return yaml.safe_load(match.group(1))


@pytest.fixture(params=[p.stem for p in AGENT_FILES], ids=[p.stem for p in AGENT_FILES])
def agent_config(request) -> tuple[str, dict]:
    path = AGENTS_DIR / f"{request.param}.md"
    return request.param, _parse_frontmatter(path)


class TestToolDenyInvariants:
    """Agent tool flags must disable dangerous capabilities."""

    def test_bash_tool_disabled(self, agent_config):
        name, config = agent_config
        tools = config.get("tools", {})
        assert tools.get("bash") is False, f"{name}: tools.bash must be false"

    def test_edit_tool_disabled(self, agent_config):
        name, config = agent_config
        tools = config.get("tools", {})
        assert tools.get("edit") is False, f"{name}: tools.edit must be false"

    def test_patch_tool_disabled(self, agent_config):
        name, config = agent_config
        tools = config.get("tools", {})
        assert tools.get("patch") is False, f"{name}: tools.patch must be false"

    def test_webfetch_tool_disabled(self, agent_config):
        name, config = agent_config
        tools = config.get("tools", {})
        assert tools.get("webfetch") is False, f"{name}: tools.webfetch must be false"

    def test_websearch_tool_disabled(self, agent_config):
        name, config = agent_config
        tools = config.get("tools", {})
        assert tools.get("websearch") is False, f"{name}: tools.websearch must be false"


class TestPermissionDenyInvariants:
    """Agent permission layer must deny bash and edit."""

    def test_bash_permission_denied(self, agent_config):
        name, config = agent_config
        perm = config.get("permission", {})
        assert perm.get("bash") == "deny", f"{name}: permission.bash must be 'deny'"

    def test_edit_permission_denied(self, agent_config):
        name, config = agent_config
        perm = config.get("permission", {})
        assert perm.get("edit") == "deny", f"{name}: permission.edit must be 'deny'"


class TestWriteRestriction:
    """Agent write permission must be restricted to /tmp/*."""

    def test_write_allows_only_tmp(self, agent_config):
        name, config = agent_config
        perm = config.get("permission", {})
        write_perm = perm.get("write", {})
        assert isinstance(write_perm, dict), f"{name}: permission.write must be a dict"
        assert write_perm.get("/tmp/*") == "allow", f"{name}: /tmp/* must be allowed"
        assert write_perm.get("*") == "deny", f"{name}: wildcard must be denied"
