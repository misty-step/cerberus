#!/usr/bin/env python3
"""Write a provider-agnostic review-run contract for the current GitHub lane."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from lib.review_run_contract import GitHubExecutionContext, ReviewRunContract, write_review_run_contract


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


def require_existing_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{label} file not found: {path}")


def load_branch_refs(pr_context_file: Path) -> tuple[str, str]:
    """Read head/base refs from the fetched PR context JSON."""

    try:
        payload = json.loads(pr_context_file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise OSError(f"unable to read PR context file {pr_context_file}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in PR context file {pr_context_file}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"invalid PR context file {pr_context_file}: expected object")

    head_ref = str(payload.get("headRefName") or "").strip()
    base_ref = str(payload.get("baseRefName") or "").strip()
    return head_ref, base_ref


def main() -> int:
    args = parse_args()
    diff_file = Path(args.diff_file)
    pr_context_file = Path(args.pr_context_file)
    output = Path(args.output)

    try:
        require_existing_file(diff_file, "diff")
        require_existing_file(pr_context_file, "PR context")
        head_ref, base_ref = load_branch_refs(pr_context_file)
        contract = ReviewRunContract(
            repository=args.repo,
            pr_number=args.pr,
            diff_file=str(diff_file),
            pr_context_file=str(pr_context_file),
            workspace_root=os.getcwd(),
            temp_dir=str(output.parent),
            head_ref=head_ref,
            base_ref=base_ref,
            github=GitHubExecutionContext(
                repo=args.repo,
                pr_number=args.pr,
                token_env_var=args.token_env_var,
            ),
        )
        write_review_run_contract(output, contract)
    except (OSError, ValueError) as exc:
        print(f"bootstrap-review-run: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
