#!/usr/bin/env python3
"""Write a provider-agnostic review-run contract for the current GitHub lane."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lib.review_run_bootstrap import (
    require_existing_file,
    write_review_run_bootstrap,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write a Cerberus review-run contract.")
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--pr", type=int, required=True, help="pull request number")
    parser.add_argument("--diff-file", required=True, help="Path to fetched PR diff")
    parser.add_argument("--pr-context-file", required=True, help="Path to fetched PR context JSON")
    parser.add_argument("--output", required=True, help="Contract output path")
    parser.add_argument(
        "--token-env-var",
        default="GH_TOKEN",
        help="Environment variable name that carries GitHub auth for runtime tools",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    diff_file = Path(args.diff_file)
    pr_context_file = Path(args.pr_context_file)
    output = Path(args.output)

    try:
        require_existing_file(diff_file, "diff")
        require_existing_file(pr_context_file, "PR context")
        write_review_run_bootstrap(
            output=output,
            repo=args.repo,
            pr_number=args.pr,
            diff_file=diff_file,
            pr_context_file=pr_context_file,
            token_env_var=args.token_env_var,
        )
    except (OSError, ValueError) as exc:
        print(f"bootstrap-review-run: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
