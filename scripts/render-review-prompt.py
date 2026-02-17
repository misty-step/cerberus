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

import sys


def main() -> None:
    from lib.review_prompt import render_review_prompt_from_env  # noqa: PLC0415

    render_review_prompt_from_env(env=sys.environ)


if __name__ == "__main__":
    main()
