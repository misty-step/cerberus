"""Typed loader for reviewer runtime profiles.

Profiles are Pi-focused runtime settings layered as:
- base profile (shared across all perspectives)
- perspective overrides

This keeps runtime policy declarative and hot-swappable while preserving
stable downstream review contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ReviewerProfilesError(RuntimeError):
    """Raised when reviewer profile config is invalid."""


@dataclass(frozen=True)
class RuntimeProfile:
    provider: str = "openrouter"
    model: str | None = None
    thinking_level: str | None = None
    tools: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    max_steps: int | None = None
    timeout: int | None = None


@dataclass(frozen=True)
class ReviewerProfilesConfig:
    version: int
    base: RuntimeProfile
    perspectives: dict[str, RuntimeProfile]

    def merged_for_perspective(self, perspective: str) -> RuntimeProfile:
        """Return merged runtime profile for the perspective.

        - scalars: override replaces base when set
        - tools: override list replaces base when provided and non-empty
        - extensions/skills: append override entries to base (dedup preserving order)
        """

        override = self.perspectives.get(perspective)
        if override is None:
            return self.base

        tools = override.tools if override.tools else self.base.tools
        extensions = _merge_unique(self.base.extensions, override.extensions)
        skills = _merge_unique(self.base.skills, override.skills)

        return RuntimeProfile(
            provider=override.provider or self.base.provider,
            model=override.model if override.model is not None else self.base.model,
            thinking_level=(
                override.thinking_level
                if override.thinking_level is not None
                else self.base.thinking_level
            ),
            tools=tools,
            extensions=extensions,
            skills=skills,
            max_steps=override.max_steps if override.max_steps is not None else self.base.max_steps,
            timeout=override.timeout if override.timeout is not None else self.base.timeout,
        )


def _merge_unique(base: list[str], extra: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in [*base, *extra]:
        if item in seen:
            continue
        out.append(item)
        seen.add(item)
    return out


def _require_mapping(value: Any, ctx: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReviewerProfilesError(f"{ctx}: expected mapping")
    return value


def _require_int(value: Any, ctx: str) -> int:
    if not isinstance(value, int):
        raise ReviewerProfilesError(f"{ctx}: expected integer")
    return value


def _require_positive_int(value: Any, ctx: str) -> int:
    n = _require_int(value, ctx)
    if n <= 0:
        raise ReviewerProfilesError(f"{ctx}: must be > 0")
    return n


def _optional_positive_int(value: Any, ctx: str) -> int | None:
    if value is None:
        return None
    return _require_positive_int(value, ctx)


def _require_str(value: Any, ctx: str) -> str:
    if not isinstance(value, str):
        raise ReviewerProfilesError(f"{ctx}: expected string")
    s = value.strip()
    if not s:
        raise ReviewerProfilesError(f"{ctx}: must be non-empty")
    return s


def _optional_str(value: Any, ctx: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, ctx)


def _optional_str_list(value: Any, ctx: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ReviewerProfilesError(f"{ctx}: expected list")
    out: list[str] = []
    for idx, item in enumerate(value):
        out.append(_require_str(item, f"{ctx}[{idx}]"))
    return out


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text())
    except FileNotFoundError:
        raise ReviewerProfilesError(f"missing config file: {path}") from None
    except yaml.YAMLError as e:
        raise ReviewerProfilesError(f"invalid YAML in {path}: {e}") from e


def _parse_profile(raw: Any, ctx: str) -> RuntimeProfile:
    data = _require_mapping(raw or {}, ctx)

    provider = _optional_str(data.get("provider"), f"{ctx}.provider") or "openrouter"
    model = _optional_str(data.get("model"), f"{ctx}.model")
    thinking_level = _optional_str(data.get("thinking_level"), f"{ctx}.thinking_level")
    tools = _optional_str_list(data.get("tools"), f"{ctx}.tools")
    extensions = _optional_str_list(data.get("extensions"), f"{ctx}.extensions")
    skills = _optional_str_list(data.get("skills"), f"{ctx}.skills")
    max_steps = _optional_positive_int(data.get("max_steps"), f"{ctx}.max_steps")
    timeout = _optional_positive_int(data.get("timeout"), f"{ctx}.timeout")

    return RuntimeProfile(
        provider=provider,
        model=model,
        thinking_level=thinking_level,
        tools=tools,
        extensions=extensions,
        skills=skills,
        max_steps=max_steps,
        timeout=timeout,
    )


def load_reviewer_profiles(path: Path) -> ReviewerProfilesConfig:
    """Load and validate reviewer profile config."""

    raw = _load_yaml(path)
    cfg = _require_mapping(raw, "config")

    version = _require_int(cfg.get("version"), "config.version")
    if version <= 0:
        raise ReviewerProfilesError("config.version: must be > 0")

    base = _parse_profile(cfg.get("base", {}), "config.base")

    perspectives_raw = cfg.get("perspectives")
    if perspectives_raw is None:
        raise ReviewerProfilesError("config.perspectives: missing required key")
    perspectives_map = _require_mapping(perspectives_raw, "config.perspectives")

    perspectives: dict[str, RuntimeProfile] = {}
    for name, profile in perspectives_map.items():
        perspective = _require_str(name, "config.perspectives key")
        perspectives[perspective] = _parse_profile(
            profile,
            f"config.perspectives[{perspective}]",
        )

    return ReviewerProfilesConfig(
        version=version,
        base=base,
        perspectives=perspectives,
    )
