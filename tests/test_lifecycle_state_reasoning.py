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
    section = _extract_section(_correctness_text(), "Lifecycle State Reasoning")
    assert section, "Could not find Lifecycle State Reasoning section"
    assert "flag" in section.lower() or "boolean" in section.lower()
    assert "later" in section.lower() or "downstream" in section.lower()
    assert "misclassif" in section.lower() or "downgrad" in section.lower()


def test_correctness_prompt_covers_retry_requeue_loops() -> None:
    """The prompt must flag loops that re-queue blocked work forever when a
    phase gate never transitions."""
    section = _extract_section(_correctness_text(), "Lifecycle State Reasoning")
    assert section, "Could not find Lifecycle State Reasoning section"
    assert "re-queue" in section.lower() or "requeue" in section.lower() or "retry loop" in section.lower()
    assert "forever" in section.lower() or "infinite" in section.lower() or "unbounded" in section.lower()


def test_correctness_prompt_covers_phase_gate_reevaluation() -> None:
    """Phase gates that evaluate once and cache the result must be flagged when
    the underlying condition can change."""
    section = _extract_section(_correctness_text(), "Lifecycle State Reasoning")
    assert section, "Could not find Lifecycle State Reasoning section"
    assert "phase" in section.lower()
    assert "re-evaluat" in section.lower() or "stale" in section.lower()


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
    """Extract content between ``heading`` and the next top-level heading.

    correctness.md uses plain-text headings (no ``#`` prefix).  A new section
    starts on any line that exactly matches a known heading from the prompt.
    """
    _known_headings = {
        "Identity",
        "Primary Focus (always check)",
        "Sentinel Error Tracing",
        "Lifecycle State Reasoning",
        "Secondary Focus (check if relevant)",
        "Infrastructure Configuration Cross-Check (mandatory when deployment/config files change)",
        "Consumer/Producer Data-Flow (mandatory when PR changes a consumer of shared data)",
        "Error Propagation Chains (mandatory when a failing call is logged but execution continues)",
        "Anti-Patterns (Do Not Flag)",
        "Knowledge Boundaries",
        "Deconfliction",
        "Verdict Criteria",
        "Review Discipline",
        "Evidence (mandatory)",
        "Output Format",
        "Few-Shot Examples",
        "JSON Schema",
    }

    lines = text.split("\n")
    in_section = False
    section_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == heading:
            in_section = True
            continue
        if in_section:
            if stripped in _known_headings:
                break
            section_lines.append(line)
    return "\n".join(section_lines)
