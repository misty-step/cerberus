"""Regression tests for spec compliance guidance in trace perspective (issue #311)."""

from pathlib import Path


ROOT = Path(__file__).parent.parent
CORRECTNESS_AGENT = ROOT / "pi" / "agents" / "correctness.md"


def test_trace_prompt_includes_spec_compliance_section() -> None:
    text = CORRECTNESS_AGENT.read_text(encoding="utf-8")

    assert "Spec Compliance" in text
    assert "acceptance criteria" in text.lower()


def test_trace_prompt_maps_ac_to_diff_code_paths() -> None:
    text = CORRECTNESS_AGENT.read_text(encoding="utf-8")

    assert "SATISFIED" in text
    assert "NOT_SATISFIED" in text
    assert "CANNOT_DETERMINE" in text


def test_trace_prompt_flags_untested_ac_as_minor() -> None:
    text = CORRECTNESS_AGENT.read_text(encoding="utf-8")

    assert "no corresponding test" in text.lower()
    assert "minor" in text.lower()
