#!/usr/bin/env python3
"""Validate reviewer perspective input against defaults/config.yml."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lib.defaults_config import ConfigError, load_defaults_config


def load_allowed_perspectives(config_path: Path) -> list[str]:
    cfg = load_defaults_config(config_path)
    return sorted({reviewer.perspective for reviewer in cfg.reviewers})


def validate_perspective(config_path: Path, perspective: str) -> tuple[bool, list[str]]:
    allowed = load_allowed_perspectives(config_path)
    return perspective in allowed, allowed


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--perspective", required=True)
    args = parser.parse_args(argv)

    try:
        is_valid, allowed = validate_perspective(args.config, args.perspective)
    except ConfigError as exc:
        print(f"::error::Unable to load defaults config: {exc}", file=sys.stderr)
        return 2

    if is_valid:
        return 0

    allowed_text = " ".join(allowed)
    print(
        f"::error::Invalid perspective: {args.perspective}. Must be one of: {allowed_text}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
