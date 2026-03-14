"""Prompt contract for lifecycle state reasoning in the correctness reviewer.

Issue #335: Cerberus under-detects bugs where success flags from earlier phases
corrupt later control flow — sticky booleans downgrading failures, blocked-work
retry loops running forever, phase gates that never re-evaluate.
"""

from pathlib import Path


ROOT = Path(__file__).parent.parent
CORRECTNESS_PROMPT = ROOT / ".opencode" / "agents" / "correctness.md"
RESILIENCE_PROMPT = ROOT / ".opencode" / "agents" / "resilience.md"


def _correctness_text() -> str:
    return CORRECTNESS_PROMPT.read_text()


def _resilience_text() -> str:
    return RESILIENCE_PROMPT.read_text()


# --- Correctness prompt contract ---


def test_correctness_prompt_has_lifecycle_state_reasoning_section() -> None:
    text = _correctness_text()
    assert "Lifecycle State Reasoning" in text
    assert "sticky" in text.lower()


def test_correctness_prompt_requires_phase_flag_audit() -> None:
    """The prompt must force the reviewer to ask what flags become sticky after
    each milestone and whether later handlers can misclassify because of them."""
    text = _correctness_text()
    assert "flag" in text.lower() or "boolean" in text.lower()
    assert "later" in text.lower() or "downstream" in text.lower()
    assert "misclassif" in text.lower() or "downgrad" in text.lower()


def test_correctness_prompt_covers_retry_requeue_loops() -> None:
    """The prompt must flag loops that re-queue blocked work forever when a
    phase gate never transitions."""
    text = _correctness_text()
    assert "re-queue" in text.lower() or "requeue" in text.lower() or "retry loop" in text.lower()
    assert "forever" in text.lower() or "infinite" in text.lower() or "unbounded" in text.lower()


def test_correctness_prompt_covers_phase_gate_reevaluation() -> None:
    """Phase gates that evaluate once and cache the result must be flagged when
    the underlying condition can change."""
    text = _correctness_text()
    assert "phase" in text.lower()
    assert "re-evaluat" in text.lower() or "stale" in text.lower()


def test_correctness_prompt_includes_cross_language_lifecycle_examples() -> None:
    """The section should include concrete patterns — not just abstract guidance."""
    text = _correctness_text()
    # At least two concrete pattern descriptions
    lifecycle_section = _extract_section(text, "Lifecycle State Reasoning")
    assert lifecycle_section, "Could not find Lifecycle State Reasoning section"
    # Should have at least pattern recognition examples
    assert "pattern" in lifecycle_section.lower() or "example" in lifecycle_section.lower() or "recognize" in lifecycle_section.lower()


def test_correctness_prompt_guards_legitimate_caching() -> None:
    """Legitimate caching of phase results (e.g. memoized auth checks) should
    not be flagged as false positives."""
    text = _correctness_text()
    lifecycle_section = _extract_section(text, "Lifecycle State Reasoning")
    assert lifecycle_section, "Could not find Lifecycle State Reasoning section"
    assert "legitimate" in lifecycle_section.lower() or "false positive" in lifecycle_section.lower() or "correctly cached" in lifecycle_section.lower()


# --- Resilience prompt contract ---


def test_resilience_prompt_covers_blocked_work_retry_storms() -> None:
    """fuse should flag retry/requeue patterns where blocked work can loop
    indefinitely when a dependency stays down."""
    text = _resilience_text()
    assert "blocked" in text.lower() or "stuck" in text.lower()
    assert "retry" in text.lower()


# --- Helpers ---


def _extract_section(text: str, heading: str) -> str:
    """Extract the content of a markdown section by heading name."""
    lines = text.split("\n")
    in_section = False
    section_lines: list[str] = []
    for line in lines:
        if heading in line and line.strip().startswith("#") or heading in line and not in_section:
            in_section = True
            continue
        if in_section:
            # Stop at the next same-level or higher heading
            stripped = line.strip()
            if stripped.startswith("#") and not stripped.startswith("###"):
                break
            section_lines.append(line)
    return "\n".join(section_lines)
