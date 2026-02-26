#!/usr/bin/env python3
"""Read and validate defaults/config.yml.

Used by shell scripts to avoid awk/grep YAML parsing.

Commands:
  reviewer-meta  Print: <name>\t<model>\t<description> for a perspective
  model-default  Print: model.default (or empty)
  model-pool     Print: model.pool entries (one per line)
  model-pool-for-tier  Print: model.tiers.<tier> entries (one per line, requires --tier)
  model-pool-for-wave  Print: model.wave_pools.<wave> entries (one per line, requires --wave)
  wave-order     Print: waves.order entries (one per line)
  wave-reviewers Print: waves.definitions.<wave>.reviewers entries (one per line, requires --wave)
  wave-max-for-tier Print: waves.max_for_tier.<tier> (or 0 if unset)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lib.defaults_config import ConfigError, load_defaults_config


def _single_line(value: str | None) -> str:
    if not value:
        return ""
    # Make shell parsing safe; descriptions with newlines render poorly anyway.
    return " ".join(value.replace("\t", " ").split())


def main(argv: list[str]) -> int:
    """Main."""
    parser = argparse.ArgumentParser(prog="read-defaults-config.py")
    sub = parser.add_subparsers(dest="cmd", required=True)

    reviewer_meta = sub.add_parser("reviewer-meta")
    reviewer_meta.add_argument("--config", required=True)
    reviewer_meta.add_argument("--perspective", required=True)

    model_default = sub.add_parser("model-default")
    model_default.add_argument("--config", required=True)

    model_pool = sub.add_parser("model-pool")
    model_pool.add_argument("--config", required=True)

    model_pool_for_tier = sub.add_parser("model-pool-for-tier")
    model_pool_for_tier.add_argument("--config", required=True)
    model_pool_for_tier.add_argument("--tier", required=True)

    model_pool_for_wave = sub.add_parser("model-pool-for-wave")
    model_pool_for_wave.add_argument("--config", required=True)
    model_pool_for_wave.add_argument("--wave", required=True)

    wave_order = sub.add_parser("wave-order")
    wave_order.add_argument("--config", required=True)

    wave_reviewers = sub.add_parser("wave-reviewers")
    wave_reviewers.add_argument("--config", required=True)
    wave_reviewers.add_argument("--wave", required=True)

    wave_max_for_tier = sub.add_parser("wave-max-for-tier")
    wave_max_for_tier.add_argument("--config", required=True)
    wave_max_for_tier.add_argument("--tier", required=True)

    args = parser.parse_args(argv)

    try:
        cfg = load_defaults_config(Path(args.config))
    except ConfigError as e:
        print(f"defaults config error: {e}", file=sys.stderr)
        return 2

    if args.cmd == "reviewer-meta":
        reviewer = cfg.reviewer_for_perspective(str(args.perspective).strip())
        if reviewer is None:
            print(
                f"defaults config error: unknown perspective: {args.perspective}",
                file=sys.stderr,
            )
            return 2
        print(
            "\t".join(
                [
                    _single_line(reviewer.name),
                    _single_line(reviewer.model),
                    _single_line(reviewer.description),
                ]
            )
        )
        return 0

    if args.cmd == "model-default":
        print(_single_line(cfg.model.default))
        return 0

    if args.cmd == "model-pool":
        for item in cfg.model.pool:
            print(_single_line(item))
        return 0

    if args.cmd == "model-pool-for-tier":
        tier = str(args.tier).strip().lower()
        if not tier:
            print(
                "defaults config error (model-pool-for-tier): --tier must be non-empty",
                file=sys.stderr,
            )
            return 2
        tier_pool = cfg.model.tiers.get(tier, [])
        for item in tier_pool:
            print(_single_line(item))
        return 0

    if args.cmd == "model-pool-for-wave":
        wave = str(args.wave).strip()
        if not wave:
            print(
                "defaults config error (model-pool-for-wave): --wave must be non-empty",
                file=sys.stderr,
            )
            return 2
        wave_pool = cfg.model.wave_pools.get(wave, [])
        for item in wave_pool:
            print(_single_line(item))
        return 0

    if args.cmd == "wave-order":
        for item in cfg.waves.order:
            print(_single_line(item))
        return 0

    if args.cmd == "wave-reviewers":
        wave = str(args.wave).strip()
        if not wave:
            print(
                "defaults config error (wave-reviewers): --wave must be non-empty",
                file=sys.stderr,
            )
            return 2
        definition = cfg.waves.definitions.get(wave)
        if definition is None:
            return 0
        for item in definition.reviewers:
            print(_single_line(item))
        return 0

    if args.cmd == "wave-max-for-tier":
        tier = str(args.tier).strip().lower()
        if not tier:
            print(
                "defaults config error (wave-max-for-tier): --tier must be non-empty",
                file=sys.stderr,
            )
            return 2
        print(str(cfg.waves.max_for_tier.get(tier, 0)))
        return 0

    print("unknown command", file=sys.stderr)  # pragma: no cover
    return 2  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
