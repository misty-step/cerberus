#!/usr/bin/env python3
"""Read and validate defaults/config.yml.

Used by shell scripts to avoid awk/grep YAML parsing.

Commands:
  reviewer-meta  Print: <name>\t<model>\t<description> for a perspective
  model-default  Print: model.default (or empty)
  model-pool     Print: model.pool entries (one per line)
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

    print("unknown command", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

