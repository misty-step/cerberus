import re
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).parent.parent
EVAL_CONFIG = ROOT / "evals" / "promptfooconfig.yaml"


@lru_cache(maxsize=1)
def _load_tests_cache() -> tuple[dict[str, Any], ...]:
    config = yaml.safe_load(EVAL_CONFIG.read_text(encoding="utf-8"))
    return tuple(config["tests"])


def _load_tests() -> list[dict[str, Any]]:
    return deepcopy(_load_tests_cache())


def _fixture(description: str) -> dict:
    fixture = next((test for test in _load_tests() if test["description"] == description), None)
    assert fixture is not None, f"Expected eval fixture {description!r} not found"
    return fixture


def _javascript_assertions(fixture: dict[str, Any]) -> list[str]:
    return [
        assertion["value"]
        for assertion in fixture["assert"]
        if assertion["type"] == "javascript"
    ]


def test_eval_config_contains_bitterblossom_metadata_reentry_fixture() -> None:
    fixture = _fixture("Security - Metadata Re-entry Recall")

    assert fixture["vars"]["perspective"] == "security"
    assert "bitterblossom#495" in fixture["vars"]["pr_body"]
    diff = fixture["vars"]["diff"]
    assert "title" in diff.lower()
    assert "branch" in diff.lower()


def test_eval_config_contains_cerberus_cloud_fail_open_fixture() -> None:
    fixture = _fixture("Security - Fail-open Default Recall")

    assert fixture["vars"]["perspective"] == "security"
    assert "cerberus-cloud#94" in fixture["vars"]["pr_body"]
    diff = fixture["vars"]["diff"]
    assert re.search(r"allow_all", diff, re.IGNORECASE)
    assert "egress" in diff.lower()
    assert "select" not in diff.lower()


def test_eval_config_contains_volume_error_leakage_fixture() -> None:
    fixture = _fixture("Security - Error Leakage And Async Side Effects Recall")

    assert fixture["vars"]["perspective"] == "security"
    assert "volume#417" in fixture["vars"]["pr_body"]
    diff = fixture["vars"]["diff"]
    assert "error.stack" in diff
    assert "auditlog" in diff.lower()


def test_new_security_recall_fixtures_assert_security_findings() -> None:
    descriptions = [
        "Security - Metadata Re-entry Recall",
        "Security - Fail-open Default Recall",
        "Security - Error Leakage And Async Side Effects Recall",
    ]

    for description in descriptions:
        fixture = _fixture(description)
        javascript_assertions = _javascript_assertions(fixture)
        assert any("output.verdict === 'FAIL'" in value for value in javascript_assertions)
        assert any("security" in value.lower() for value in javascript_assertions)


def test_new_security_recall_fixtures_use_consistent_security_signal_matching() -> None:
    descriptions = [
        "Security - Metadata Re-entry Recall",
        "Security - Fail-open Default Recall",
        "Security - Error Leakage And Async Side Effects Recall",
    ]

    for description in descriptions:
        fixture = _fixture(description)
        assert any(
            "security|injection|exposure" in value
            for value in _javascript_assertions(fixture)
        )


def test_async_side_effect_fixture_requires_both_leakage_and_async_signals() -> None:
    fixture = _fixture("Security - Error Leakage And Async Side Effects Recall")
    javascript = "\n".join(_javascript_assertions(fixture))

    assert "error|stack|prompt" in javascript
    assert "audit|async" in javascript
