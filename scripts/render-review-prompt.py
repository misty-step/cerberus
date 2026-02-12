#!/usr/bin/env python3
"""Render the reviewer prompt template with PR context.

Used by `scripts/run-reviewer.sh` so prompt hardening is unit-testable.

Environment:
  CERBERUS_ROOT   (required) action root containing templates/
  DIFF_FILE       (required) path to PR diff file
  PERSPECTIVE     (required) reviewer perspective (security, etc)
  PROMPT_OUTPUT   (required) output path for rendered prompt markdown
  CERBERUS_CONTEXT (optional) maintainer-provided project context injected into prompt

PR context (either):
  GH_PR_CONTEXT   path to JSON file from `gh pr view --json ...`
  or GH_PR_TITLE, GH_PR_AUTHOR, GH_HEAD_BRANCH, GH_BASE_BRANCH, GH_PR_BODY
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        print(f"missing required env var: {name}", file=sys.stderr)
        raise SystemExit(2)
    return value


def main() -> None:
    from lib.review_prompt import render_review_prompt_file  # noqa: PLC0415

    cerberus_root = Path(_require_env("CERBERUS_ROOT"))
    diff_file = _require_env("DIFF_FILE")
    perspective = _require_env("PERSPECTIVE")
    output_path = Path(_require_env("PROMPT_OUTPUT"))

    render_review_prompt_file(
        cerberus_root=cerberus_root,
        env=os.environ,
        diff_file=diff_file,
        perspective=perspective,
        output_path=output_path,
    )


if __name__ == "__main__":
    main()
