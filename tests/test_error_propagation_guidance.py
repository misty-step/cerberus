from pathlib import Path

import yaml


ROOT = Path(__file__).parent.parent
CORRECTNESS_AGENT = ROOT / ".opencode" / "agents" / "correctness.md"
EVAL_CONFIG = ROOT / "evals" / "promptfooconfig.yaml"


def test_correctness_agent_has_error_propagation_chains_section() -> None:
    text = CORRECTNESS_AGENT.read_text(encoding="utf-8")

    assert "Error Propagation Chains" in text


def test_error_propagation_guidance_mentions_logged_only_errors() -> None:
    text = CORRECTNESS_AGENT.read_text(encoding="utf-8")

    assert "caught-and-logged" in text
    assert "not returned, not re-raised" in text
    assert "result of the failing call" in text


def test_error_propagation_guidance_requires_downstream_trace() -> None:
    text = CORRECTNESS_AGENT.read_text(encoding="utf-8")

    assert "Trace every use of that value" in text
    assert "Name the specific variable" in text
    assert "specific crashing line" in text


def test_error_propagation_guidance_calls_out_safe_fallback_exemptions() -> None:
    text = CORRECTNESS_AGENT.read_text(encoding="utf-8")

    assert "safe explicit fallback" in text
    assert "checks the result for nil/zero before use" in text
    assert "returns immediately after logging" in text


def test_error_propagation_guidance_covers_cross_language_patterns() -> None:
    text = CORRECTNESS_AGENT.read_text(encoding="utf-8")

    assert "Go:" in text
    assert "Python:" in text
    assert "JS/TS:" in text
    assert "log.Warn" in text


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
