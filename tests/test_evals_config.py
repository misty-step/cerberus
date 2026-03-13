import re
from functools import lru_cache
from pathlib import Path

import yaml


ROOT = Path(__file__).parent.parent
EVAL_CONFIG = ROOT / "evals" / "promptfooconfig.yaml"


@lru_cache(maxsize=1)
def _load_tests() -> list[dict]:
    config = yaml.safe_load(EVAL_CONFIG.read_text(encoding="utf-8"))
    return config["tests"]


def _fixture(description: str) -> dict:
    fixture = next((test for test in _load_tests() if test["description"] == description), None)
    assert fixture is not None, f"Expected eval fixture {description!r} not found"
    return fixture


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
    assert re.search(r"select", diff, re.IGNORECASE)


def test_eval_config_contains_volume_error_leakage_fixture() -> None:
    fixture = _fixture("Security - Error Leakage And Async Side Effects Recall")

    assert fixture["vars"]["perspective"] == "security"
    assert "volume#417" in fixture["vars"]["pr_body"]
    diff = fixture["vars"]["diff"]
    assert "error" in diff.lower()
    assert "log" in diff.lower()


def test_new_security_recall_fixtures_assert_security_findings() -> None:
    descriptions = [
        "Security - Metadata Re-entry Recall",
        "Security - Fail-open Default Recall",
        "Security - Error Leakage And Async Side Effects Recall",
    ]

    for description in descriptions:
        fixture = _fixture(description)
        javascript_assertions = [
            assertion["value"]
            for assertion in fixture["assert"]
            if assertion["type"] == "javascript"
        ]
        assert any("output.verdict === 'FAIL'" in value for value in javascript_assertions)
        assert any("security" in value.lower() for value in javascript_assertions)
