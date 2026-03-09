from pathlib import Path

import yaml


ROOT = Path(__file__).parent.parent
REVIEW_PROMPT = ROOT / "templates" / "review-prompt.md"
ARCHITECTURE_AGENT = ROOT / ".opencode" / "agents" / "architecture.md"
MAINTAINABILITY_AGENT = ROOT / ".opencode" / "agents" / "maintainability.md"
EVAL_CONFIG = ROOT / "evals" / "promptfooconfig.yaml"


def test_review_prompt_expands_scope_for_workflow_and_infra_regressions() -> None:
    text = REVIEW_PROMPT.read_text(encoding="utf-8")

    assert "## Workflow / Infra Adjacent Regression Pass" in text
    assert "deleted files" in text
    assert "renamed status contexts" in text
    assert "changed enforcement flags" in text
    assert "neighboring workflows or scripts" in text


def test_architecture_and_maintainability_agents_reinforce_adjacent_regression_checklist() -> None:
    architecture_text = ARCHITECTURE_AGENT.read_text(encoding="utf-8")
    maintainability_text = MAINTAINABILITY_AGENT.read_text(encoding="utf-8")

    for text in (architecture_text, maintainability_text):
        assert "workflow or infra PRs" in text
        assert "deleted files" in text
        assert "renamed status contexts" in text
        assert "changed enforcement flags" in text
        assert "neighboring workflows or scripts" in text


def test_eval_config_contains_volume_407_adjacent_regression_fixture() -> None:
    config = yaml.safe_load(EVAL_CONFIG.read_text(encoding="utf-8"))

    fixture = next(
        test
        for test in config["tests"]
        if test["description"] == "Architecture - Workflow Adjacent Regression Recall"
    )

    assert "volume#407" in fixture["vars"]["pr_body"]
    assert "trufflehog" in fixture["vars"]["diff"].lower()
    javascript_assertions = [
        assertion["value"]
        for assertion in fixture["assert"]
        if assertion["type"] == "javascript"
    ]
    assert any("output.verdict === 'FAIL'" in value for value in javascript_assertions)
    assert any("deleted" in value.lower() or "trufflehog" in value.lower() for value in javascript_assertions)
