"""Tests for lib.reviewer_profiles."""

from pathlib import Path

import pytest

from lib.reviewer_profiles import (
    ReviewerProfilesError,
    RuntimeProfile,
    load_reviewer_profiles,
)


def write_config(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "reviewer-profiles.yml"
    p.write_text(content)
    return p


class TestLoadReviewerProfiles:
    def test_minimal_valid_config(self, tmp_path: Path) -> None:
        path = write_config(
            tmp_path,
            """
version: 1
base: {}
perspectives:
  correctness: {}
""",
        )

        cfg = load_reviewer_profiles(path)
        assert cfg.version == 1
        assert cfg.base.provider == "openrouter"
        assert "correctness" in cfg.perspectives

    def test_merged_profile_scalar_and_list_behavior(self, tmp_path: Path) -> None:
        path = write_config(
            tmp_path,
            """
version: 1
base:
  provider: openrouter
  model: moonshotai/kimi-k2.5
  thinking_level: medium
  tools: [read, grep, find, ls, write]
  extensions: [pi/extensions/reviewer-guard.ts]
  skills: [pi/skills/base/SKILL.md]
  max_steps: 25
  timeout: 600
perspectives:
  security:
    model: minimax/minimax-m2.5
    thinking_level: high
    # tools override replaces base tools when provided.
    tools: [read, grep, find, ls, write, bash]
    # extensions/skills append (dedup preserving order).
    extensions: [pi/extensions/runtime-telemetry.ts]
    skills: [pi/skills/security/SKILL.md]
""",
        )

        cfg = load_reviewer_profiles(path)
        merged = cfg.merged_for_perspective("security")

        assert merged.provider == "openrouter"
        assert merged.model == "minimax/minimax-m2.5"
        assert merged.thinking_level == "high"
        assert merged.tools == ["read", "grep", "find", "ls", "write", "bash"]
        assert merged.extensions == [
            "pi/extensions/reviewer-guard.ts",
            "pi/extensions/runtime-telemetry.ts",
        ]
        assert merged.skills == [
            "pi/skills/base/SKILL.md",
            "pi/skills/security/SKILL.md",
        ]
        assert merged.max_steps == 25
        assert merged.timeout == 600

    def test_unknown_perspective_returns_base(self, tmp_path: Path) -> None:
        path = write_config(
            tmp_path,
            """
version: 1
base:
  model: moonshotai/kimi-k2.5
perspectives:
  correctness: {}
""",
        )

        cfg = load_reviewer_profiles(path)
        merged = cfg.merged_for_perspective("nonexistent")
        assert merged == cfg.base

    def test_missing_version_raises(self, tmp_path: Path) -> None:
        path = write_config(
            tmp_path,
            """
base: {}
perspectives: {}
""",
        )
        with pytest.raises(ReviewerProfilesError, match="config.version"):
            load_reviewer_profiles(path)

    def test_missing_perspectives_raises(self, tmp_path: Path) -> None:
        path = write_config(
            tmp_path,
            """
version: 1
base: {}
""",
        )
        with pytest.raises(ReviewerProfilesError, match="config.perspectives"):
            load_reviewer_profiles(path)

    def test_invalid_positive_int_raises(self, tmp_path: Path) -> None:
        path = write_config(
            tmp_path,
            """
version: 1
base:
  timeout: 0
perspectives:
  correctness: {}
""",
        )
        with pytest.raises(ReviewerProfilesError, match="must be > 0"):
            load_reviewer_profiles(path)

    def test_invalid_list_field_type_raises(self, tmp_path: Path) -> None:
        path = write_config(
            tmp_path,
            """
version: 1
base:
  tools: read
perspectives:
  correctness: {}
""",
        )
        with pytest.raises(ReviewerProfilesError, match="expected list"):
            load_reviewer_profiles(path)

    def test_profile_dataclass_defaults(self) -> None:
        p = RuntimeProfile()
        assert p.provider == "openrouter"
        assert p.tools == []
        assert p.extensions == []
        assert p.skills == []
