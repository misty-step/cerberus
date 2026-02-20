"""Tests for lib.defaults_config — load_defaults_config and helpers."""

import pytest
from pathlib import Path

from lib.defaults_config import (
    ConfigError,
    DefaultsConfig,
    ModelConfig,
    Reviewer,
    load_defaults_config,
)


def write_config(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "config.yml"
    p.write_text(content)
    return p


class TestLoadDefaultsConfig:
    def test_minimal_valid_config(self, tmp_path):
        path = write_config(tmp_path, """
reviewers:
  - name: APOLLO
    perspective: correctness
""")
        cfg = load_defaults_config(path)
        assert len(cfg.reviewers) == 1
        assert cfg.reviewers[0].name == "APOLLO"
        assert cfg.reviewers[0].perspective == "correctness"
        assert cfg.reviewers[0].model is None
        assert cfg.reviewers[0].description is None
        assert cfg.model == ModelConfig()

    def test_full_config_with_model(self, tmp_path):
        path = write_config(tmp_path, """
model:
  default: openrouter/kimi-k2.5
  pool:
    - openrouter/a
    - openrouter/b
reviewers:
  - name: SENTINEL
    perspective: security
    model: openrouter/specific
    description: Security reviewer
""")
        cfg = load_defaults_config(path)
        assert cfg.model.default == "openrouter/kimi-k2.5"
        assert cfg.model.pool == ["openrouter/a", "openrouter/b"]
        assert cfg.reviewers[0].model == "openrouter/specific"
        assert cfg.reviewers[0].description == "Security reviewer"

    def test_legacy_list_format(self, tmp_path):
        path = write_config(tmp_path, """
- name: APOLLO
  perspective: correctness
""")
        cfg = load_defaults_config(path)
        assert len(cfg.reviewers) == 1
        assert cfg.reviewers[0].name == "APOLLO"

    def test_missing_reviewers_key(self, tmp_path):
        path = write_config(tmp_path, "model:\n  default: x\n")
        with pytest.raises(ConfigError, match="missing required key"):
            load_defaults_config(path)

    def test_empty_reviewers_list(self, tmp_path):
        path = write_config(tmp_path, "reviewers: []\n")
        with pytest.raises(ConfigError, match="must be non-empty"):
            load_defaults_config(path)

    def test_reviewer_not_a_mapping(self, tmp_path):
        path = write_config(tmp_path, "reviewers:\n  - just_a_string\n")
        with pytest.raises(ConfigError, match="expected mapping"):
            load_defaults_config(path)

    def test_reviewer_missing_name(self, tmp_path):
        path = write_config(tmp_path, """
reviewers:
  - perspective: correctness
""")
        with pytest.raises(ConfigError, match="name.*expected string"):
            load_defaults_config(path)

    def test_reviewer_missing_perspective(self, tmp_path):
        path = write_config(tmp_path, """
reviewers:
  - name: APOLLO
""")
        with pytest.raises(ConfigError, match="perspective.*expected string"):
            load_defaults_config(path)

    def test_reviewer_empty_name(self, tmp_path):
        path = write_config(tmp_path, """
reviewers:
  - name: ""
    perspective: correctness
""")
        with pytest.raises(ConfigError, match="must be non-empty"):
            load_defaults_config(path)

    def test_reviewer_non_string_name(self, tmp_path):
        path = write_config(tmp_path, """
reviewers:
  - name: 42
    perspective: correctness
""")
        with pytest.raises(ConfigError, match="expected string"):
            load_defaults_config(path)

    def test_model_not_a_mapping(self, tmp_path):
        path = write_config(tmp_path, """
model: just_a_string
reviewers:
  - name: A
    perspective: b
""")
        with pytest.raises(ConfigError, match="expected mapping"):
            load_defaults_config(path)

    def test_model_pool_not_a_list(self, tmp_path):
        path = write_config(tmp_path, """
model:
  pool: not_a_list
reviewers:
  - name: A
    perspective: b
""")
        with pytest.raises(ConfigError, match="expected list"):
            load_defaults_config(path)

    def test_model_pool_item_not_string(self, tmp_path):
        path = write_config(tmp_path, """
model:
  pool:
    - 42
reviewers:
  - name: A
    perspective: b
""")
        with pytest.raises(ConfigError, match="expected string"):
            load_defaults_config(path)

    def test_optional_str_non_string(self, tmp_path):
        path = write_config(tmp_path, """
reviewers:
  - name: A
    perspective: b
    model: 42
""")
        with pytest.raises(ConfigError, match="expected string"):
            load_defaults_config(path)

    def test_optional_str_empty_becomes_none(self, tmp_path):
        path = write_config(tmp_path, """
reviewers:
  - name: A
    perspective: b
    model: "   "
""")
        cfg = load_defaults_config(path)
        assert cfg.reviewers[0].model is None

    def test_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent.yml"
        with pytest.raises(ConfigError, match="missing config file"):
            load_defaults_config(path)

    def test_invalid_yaml(self, tmp_path):
        path = write_config(tmp_path, "reviewers: [\n")
        with pytest.raises(ConfigError, match="invalid YAML"):
            load_defaults_config(path)

    def test_top_level_not_mapping_or_list(self, tmp_path):
        path = write_config(tmp_path, '"just a string"\n')
        with pytest.raises(ConfigError, match="expected mapping"):
            load_defaults_config(path)

    def test_reviewers_not_a_list(self, tmp_path):
        path = write_config(tmp_path, "reviewers: not_a_list\n")
        with pytest.raises(ConfigError, match="expected list"):
            load_defaults_config(path)

    def test_model_default_non_string(self, tmp_path):
        path = write_config(tmp_path, """
model:
  default: 42
reviewers:
  - name: A
    perspective: b
""")
        with pytest.raises(ConfigError, match="expected string"):
            load_defaults_config(path)


class TestReviewerForPerspective:
    def test_found(self):
        cfg = DefaultsConfig(
            reviewers=[
                Reviewer(name="A", perspective="correctness"),
                Reviewer(name="B", perspective="security"),
            ],
            model=ModelConfig(),
        )
        r = cfg.reviewer_for_perspective("security")
        assert r is not None
        assert r.name == "B"

    def test_not_found(self):
        cfg = DefaultsConfig(
            reviewers=[Reviewer(name="A", perspective="correctness")],
            model=ModelConfig(),
        )
        assert cfg.reviewer_for_perspective("security") is None
