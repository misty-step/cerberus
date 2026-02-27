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
    wave_pools: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class WaveGateConfig:
    """Data class for per-wave gating rules."""
    block_on_critical: bool = True
    block_on_major: bool = True
    block_on_skip: bool = True
    skip_tolerance: int = 0  # allow up to N skips before blocking (default: block on any)


@dataclass(frozen=True)
class WaveDefinition:
    """Data class for one wave definition."""
    reviewers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WavesConfig:
    """Data class for cascading wave config."""
    enabled: bool = False
    order: list[str] = field(default_factory=list)
    max_for_tier: dict[str, int] = field(default_factory=dict)
    gate: WaveGateConfig = field(default_factory=WaveGateConfig)
    definitions: dict[str, WaveDefinition] = field(default_factory=dict)


@dataclass(frozen=True)
class DefaultsConfig:
    """Data class for Defaults Config."""
    reviewers: list[Reviewer]
    model: ModelConfig
    waves: WavesConfig = field(default_factory=WavesConfig)

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


def _require_bool(value: Any, ctx: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{ctx}: expected boolean")
    return value


def _require_positive_int(value: Any, ctx: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{ctx}: expected integer")
    if value < 1:
        raise ConfigError(f"{ctx}: must be >= 1")
    return value


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
        wave_pools: dict[str, list[str]] = {}
        wave_pools_raw = model_cfg.get("wave_pools")
        if wave_pools_raw is not None:
            wave_pools_map = _require_mapping(wave_pools_raw, "config.model.wave_pools")
            for wave, models in wave_pools_map.items():
                wave_name = _require_str(wave, f"config.model.wave_pools key '{wave}'")
                wave_pools[wave_name] = _require_str_list(
                    models, f"config.model.wave_pools[{wave_name}]"
                )
        model = ModelConfig(default=model_default, pool=pool, tiers=tiers, wave_pools=wave_pools)

    waves_raw = cfg.get("waves")
    waves = WavesConfig()
    if waves_raw is not None:
        waves_cfg = _require_mapping(waves_raw, "config.waves")

        enabled = bool(waves_cfg.get("enabled", False))
        if "enabled" in waves_cfg:
            enabled = _require_bool(waves_cfg.get("enabled"), "config.waves.enabled")

        order: list[str] = []
        if "order" in waves_cfg:
            order = _require_str_list(waves_cfg.get("order"), "config.waves.order")

        max_for_tier: dict[str, int] = {}
        max_for_tier_raw = waves_cfg.get("max_for_tier")
        if max_for_tier_raw is not None:
            max_for_tier_map = _require_mapping(max_for_tier_raw, "config.waves.max_for_tier")
            for tier, value in max_for_tier_map.items():
                tier_name = _require_str(tier, f"config.waves.max_for_tier key '{tier}'")
                max_for_tier[tier_name] = _require_positive_int(
                    value, f"config.waves.max_for_tier[{tier_name}]"
                )

        gate = WaveGateConfig()
        gate_raw = waves_cfg.get("gate")
        if gate_raw is not None:
            gate_cfg = _require_mapping(gate_raw, "config.waves.gate")
            raw_tol = gate_cfg.get("skip_tolerance", 0)
            if isinstance(raw_tol, bool) or not isinstance(raw_tol, int) or raw_tol < 0:
                raise ConfigError("config.waves.gate.skip_tolerance: expected non-negative integer")
            gate = WaveGateConfig(
                block_on_critical=_require_bool(
                    gate_cfg.get("block_on_critical", True),
                    "config.waves.gate.block_on_critical",
                ),
                block_on_major=_require_bool(
                    gate_cfg.get("block_on_major", True),
                    "config.waves.gate.block_on_major",
                ),
                block_on_skip=_require_bool(
                    gate_cfg.get("block_on_skip", True),
                    "config.waves.gate.block_on_skip",
                ),
                skip_tolerance=raw_tol,
            )

        definitions: dict[str, WaveDefinition] = {}
        definitions_raw = waves_cfg.get("definitions")
        if definitions_raw is not None:
            definitions_map = _require_mapping(definitions_raw, "config.waves.definitions")
            for wave, item in definitions_map.items():
                wave_name = _require_str(wave, f"config.waves.definitions key '{wave}'")
                definition = _require_mapping(item, f"config.waves.definitions[{wave_name}]")
                reviewers_for_wave = _require_str_list(
                    definition.get("reviewers"),
                    f"config.waves.definitions[{wave_name}].reviewers",
                )
                definitions[wave_name] = WaveDefinition(reviewers=reviewers_for_wave)

        if definitions and not order:
            order = list(definitions.keys())
        if len(order) != len(set(order)):
            raise ConfigError("config.waves.order: duplicate wave names are not allowed")
        for wave_name in order:
            if wave_name not in definitions:
                raise ConfigError(
                    f"config.waves.order references undefined wave '{wave_name}'"
                )

        known_reviewers = {reviewer.name for reviewer in reviewers}
        for wave_name, definition in definitions.items():
            if not definition.reviewers:
                raise ConfigError(
                    f"config.waves.definitions[{wave_name}].reviewers: must be non-empty"
                )
            for reviewer_name in definition.reviewers:
                if reviewer_name not in known_reviewers:
                    raise ConfigError(
                        "config.waves.definitions"
                        f"[{wave_name}].reviewers references unknown reviewer '{reviewer_name}'"
                    )

        waves = WavesConfig(
            enabled=enabled,
            order=order,
            max_for_tier=max_for_tier,
            gate=gate,
            definitions=definitions,
        )

    return DefaultsConfig(reviewers=reviewers, model=model, waves=waves)
