"""Verify review prompt and agents include defaults-change awareness guidance.

Regression test for issue #93: reviewers missed latent bugs exposed by
defaults changes because the scope rules limited review to modified lines.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
REVIEW_PROMPT = ROOT / "templates" / "review-prompt.md"
AGENTS_DIR = ROOT / ".opencode" / "agents"


class TestReviewPromptDefaultsAwareness:
    """The shared review prompt must instruct all reviewers to trace
    newly-defaulted code paths."""

    def test_contains_defaults_change_section(self):
        text = REVIEW_PROMPT.read_text()
        assert "## Defaults Change Awareness" in text

    def test_scope_includes_unchanged_defaulted_paths(self):
        text = REVIEW_PROMPT.read_text()
        assert "newly-defaulted code path is IN SCOPE" in text

    def test_instructs_tracing_default_path(self):
        text = REVIEW_PROMPT.read_text()
        assert "Trace the full execution path" in text

    def test_instructs_flagging_experimental_paths(self):
        text = REVIEW_PROMPT.read_text()
        assert "previously experimental or opt-in" in text

    def test_defaults_section_before_trust_boundaries(self):
        """Defaults awareness must come before Trust Boundaries so reviewers
        see it as part of scope expansion, not as a separate concern."""
        text = REVIEW_PROMPT.read_text()
        defaults_pos = text.index("## Defaults Change Awareness")
        trust_pos = text.index("## Trust Boundaries")
        assert defaults_pos < trust_pos


class TestAgentDefaultsAwareness:
    """APOLLO and VULCAN must reinforce defaults-change guidance
    in their own perspective-specific terms."""

    def test_apollo_mentions_defaults_changes(self):
        text = (AGENTS_DIR / "correctness.md").read_text()
        assert "defaults change" in text.lower()

    def test_apollo_instructs_tracing_defaulted_path(self):
        text = (AGENTS_DIR / "correctness.md").read_text()
        assert "newly-defaulted path" in text

    def test_vulcan_mentions_defaults_changes(self):
        text = (AGENTS_DIR / "performance.md").read_text()
        assert "defaults change" in text.lower()

    def test_vulcan_instructs_checking_performance_at_scale(self):
        text = (AGENTS_DIR / "performance.md").read_text()
        assert "newly-defaulted path" in text
