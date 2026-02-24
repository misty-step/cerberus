"""Typed loader for defaults/config.yml.

Centralizes parsing/validation so shell scripts don't awk/grep YAML.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(RuntimeError):
    """Data class for Config Error."""
    pass


@dataclass(frozen=True)
class Reviewer:
    """Data class for Reviewer."""
    name: str
    perspective: str
    model: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class ModelConfig:
    """Data class for Model Config."""
    default: str | None = None
    pool: list[str] = field(default_factory=list)
    tiers: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class DefaultsConfig:
    """Data class for Defaults Config."""
    reviewers: list[Reviewer]
    model: ModelConfig

    def reviewer_for_perspective(self, perspective: str) -> Reviewer | None:
        """Reviewer for perspective."""
        for reviewer in self.reviewers:
            if reviewer.perspective == perspective:
                return reviewer
        return None


def _require_mapping(value: Any, ctx: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{ctx}: expected mapping")
    return value


def _require_list(value: Any, ctx: str) -> list[Any]:
    if not isinstance(value, list):
        raise ConfigError(f"{ctx}: expected list")
    return value


def _require_str_list(value: Any, ctx: str) -> list[str]:
    raw = _require_list(value, ctx)
    out: list[str] = []
    for idx, item in enumerate(raw):
        out.append(_require_str(item, f"{ctx}[{idx}]"))
    return out


def _require_str(value: Any, ctx: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{ctx}: expected string")
    s = value.strip()
    if not s:
        raise ConfigError(f"{ctx}: must be non-empty")
    return s


def _optional_str(value: Any, ctx: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"{ctx}: expected string")
    s = value.strip()
    return s or None


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text())
    except FileNotFoundError:
        raise ConfigError(f"missing config file: {path}") from None
    except yaml.YAMLError as e:
        raise ConfigError(f"invalid YAML in {path}: {e}") from e


def load_defaults_config(path: Path) -> DefaultsConfig:
    """Load defaults config."""
    raw = _load_yaml(path)

    # Legacy/loose format: top-level list means "reviewers".
    if isinstance(raw, list):
        raw = {"reviewers": raw}

    cfg = _require_mapping(raw, "config")

    reviewers_raw = cfg.get("reviewers")
    if reviewers_raw is None:
        raise ConfigError("config.reviewers: missing required key")
    reviewers_list = _require_list(reviewers_raw, "config.reviewers")
    if not reviewers_list:
        raise ConfigError("config.reviewers: must be non-empty")

    reviewers: list[Reviewer] = []
    for idx, item in enumerate(reviewers_list):
        reviewer = _require_mapping(item, f"config.reviewers[{idx}]")
        name = _require_str(reviewer.get("name"), f"config.reviewers[{idx}].name")
        perspective = _require_str(
            reviewer.get("perspective"), f"config.reviewers[{idx}].perspective"
        )
        model = _optional_str(reviewer.get("model"), f"config.reviewers[{idx}].model")
        description = _optional_str(
            reviewer.get("description"), f"config.reviewers[{idx}].description"
        )
        reviewers.append(
            Reviewer(
                name=name,
                perspective=perspective,
                model=model,
                description=description,
            )
        )

    model_cfg_raw = cfg.get("model")
    model = ModelConfig()
    if model_cfg_raw is not None:
        model_cfg = _require_mapping(model_cfg_raw, "config.model")
        model_default = _optional_str(model_cfg.get("default"), "config.model.default")
        pool_raw = model_cfg.get("pool")
        pool: list[str] = []
        if pool_raw is not None:
            pool = _require_str_list(pool_raw, "config.model.pool")
        tiers: dict[str, list[str]] = {}
        tiers_raw = model_cfg.get("tiers")
        if tiers_raw is not None:
            tiers_map = _require_mapping(tiers_raw, "config.model.tiers")
            for tier, models in tiers_map.items():
                tier_name = _require_str(tier, f"config.model.tiers key '{tier}'")
                tiers[tier_name] = _require_str_list(models, f"config.model.tiers[{tier_name}]")
        model = ModelConfig(default=model_default, pool=pool, tiers=tiers)

    return DefaultsConfig(reviewers=reviewers, model=model)
