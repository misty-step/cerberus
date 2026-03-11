from pathlib import Path

import yaml


ROOT = Path(__file__).parent.parent
CORRECTNESS_AGENT = ROOT / ".opencode" / "agents" / "correctness.md"
EVAL_CONFIG = ROOT / "evals" / "promptfooconfig.yaml"
CORRECTNESS_TEXT = CORRECTNESS_AGENT.read_text(encoding="utf-8")


def test_correctness_agent_has_error_propagation_chains_section() -> None:
    assert "Error Propagation Chains" in CORRECTNESS_TEXT


def test_error_propagation_guidance_mentions_logged_only_errors() -> None:
    assert "caught-and-logged" in CORRECTNESS_TEXT
    assert "not returned, not re-raised" in CORRECTNESS_TEXT
    assert "result of the failing call" in CORRECTNESS_TEXT


def test_error_propagation_guidance_requires_downstream_trace() -> None:
    assert "Trace every use of that value" in CORRECTNESS_TEXT
    assert "Name the specific variable" in CORRECTNESS_TEXT
    assert "specific crashing line" in CORRECTNESS_TEXT


def test_error_propagation_guidance_calls_out_safe_fallback_exemptions() -> None:
    assert "safe explicit fallback" in CORRECTNESS_TEXT
    assert "checks the result for nil/zero before use" in CORRECTNESS_TEXT
    assert "returns immediately after logging" in CORRECTNESS_TEXT


def test_error_propagation_guidance_covers_cross_language_patterns() -> None:
    assert "Go:" in CORRECTNESS_TEXT
    assert "Python:" in CORRECTNESS_TEXT
    assert "JS/TS:" in CORRECTNESS_TEXT
    assert "log.Warn" in CORRECTNESS_TEXT


def test_eval_config_contains_swallowed_error_fixture() -> None:
    config = yaml.safe_load(EVAL_CONFIG.read_text(encoding="utf-8"))

    fixture = next(
        (test for test in config["tests"] if test["description"] == "Correctness - Swallowed Error Propagation"),
        None,
    )
    assert fixture is not None, "Expected swallowed-error eval fixture not found"

    assert "log.Warn" in fixture["vars"]["diff"]
    assert "resp.Name" in fixture["vars"]["diff"]
    javascript_assertions = [
        assertion["value"]
        for assertion in fixture["assert"]
        if assertion["type"] == "javascript"
    ]
    assert any("major" in value.lower() or "critical" in value.lower() for value in javascript_assertions)
    assert any("resp" in value.lower() for value in javascript_assertions)
