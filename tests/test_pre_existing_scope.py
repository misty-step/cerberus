"""Verify review prompt scopes findings to PR-introduced changes only.

Regression test for issue #103: reviewers flagged pre-existing conditions
(e.g., "this file is too large") that existed before the PR, creating noise
and making authors responsible for inherited tech debt.
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent
REVIEW_PROMPT = ROOT / "templates" / "review-prompt.md"
AGENTS_DIR = ROOT / ".opencode" / "agents"


class TestReviewPromptPreExistingScope:
    """The shared review prompt must instruct reviewers to flag only
    the delta introduced by the PR, not pre-existing conditions."""

    def test_contains_pre_existing_conditions_section(self):
        text = REVIEW_PROMPT.read_text()
        assert "### Pre-Existing Conditions" in text

    def test_instructs_not_to_flag_pre_existing(self):
        text = REVIEW_PROMPT.read_text()
        assert "do NOT flag them as findings" in text

    def test_instructs_delta_only(self):
        text = REVIEW_PROMPT.read_text()
        assert "flag only the delta" in text

    def test_instructs_no_severity_inflation(self):
        text = REVIEW_PROMPT.read_text()
        assert "Do NOT inflate severity" in text

    def test_pre_existing_section_inside_scope_rules(self):
        """Pre-existing conditions guidance must be within scope rules,
        before evidence rules."""
        text = REVIEW_PROMPT.read_text()
        scope_pos = text.index("## Scope Rules")
        pre_existing_pos = text.index("### Pre-Existing Conditions")
        evidence_pos = text.index("## Evidence Rules")
        assert scope_pos < pre_existing_pos < evidence_pos


class TestArtemisPreExistingExample:
    """ARTEMIS (maintainability) must include a negative example for
    pre-existing condition findings, since this reviewer is most likely
    to flag accumulated complexity."""

    def test_artemis_has_pre_existing_bad_example(self):
        text = (AGENTS_DIR / "maintainability.md").read_text()
        assert "pre-existing condition" in text.lower()

    def test_artemis_bad_example_shows_component_size(self):
        text = (AGENTS_DIR / "maintainability.md").read_text()
        assert "Flag only the delta introduced by this PR" in text
