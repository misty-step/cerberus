"""Prompt contract for sentinel error tracing in the correctness reviewer."""

from pathlib import Path


ROOT = Path(__file__).parent.parent
CORRECTNESS_PROMPT = ROOT / "pi" / "agents" / "correctness.md"


def _prompt_text() -> str:
    return CORRECTNESS_PROMPT.read_text()


def test_correctness_prompt_has_sentinel_error_tracing_section() -> None:
    text = _prompt_text()
    assert "Sentinel Error Tracing" in text
    assert "Sentinel errors carry semantic meaning" in text


def test_correctness_prompt_traces_assignment_and_caller_consequence() -> None:
    text = _prompt_text()
    assert "Identify all return sites of the sentinel" in text
    assert "Trace callers" in text
    assert "loop termination" in text
    assert "state machine" in text


def test_correctness_prompt_includes_cross_language_examples() -> None:
    text = _prompt_text()
    assert "Go: `if err != nil { return nil, ErrSentinel }`" in text
    assert "Python: `except Exception: raise StopIteration`" in text
    assert 'JS: `catch(e) { return null }`' in text
    assert "Rust: returning `None` from `Option` when `Err` is semantically correct" in text


def test_correctness_prompt_guards_legitimate_empty_paths() -> None:
    text = _prompt_text()
    assert "legitimate empty/done path" in text
    assert "Do NOT flag all sentinel usage" in text
