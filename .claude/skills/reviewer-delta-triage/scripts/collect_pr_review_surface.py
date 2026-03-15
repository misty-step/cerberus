#!/usr/bin/env python3
"""Collect the full review surface for a PR: comments, reviews, and inline review comments.

GitHub stores review feedback in three separate channels:
  1. PR comments      — top-level conversation (gh pr view --json comments)
  2. Review bodies    — summary text with each review (gh pr view --json reviews)
  3. Inline comments  — line-level code comments (REST: pulls/{pr}/comments)

Channel 3 is NOT available via `gh pr view --json`. This script fetches all three
and merges them into a single JSON document.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


class GhCommandError(RuntimeError):
    """Raised when a gh CLI command fails or returns non-JSON output."""


PR_VIEW_FIELDS = "number,title,url,body,files,comments,reviews"


def run_json(cmd: list[str]) -> object:
    try:
        result = subprocess.run(cmd, text=True, capture_output=True, check=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        message = f"gh command failed ({exc.returncode}): {' '.join(cmd)}"
        if detail:
            message = f"{message}: {detail}"
        raise GhCommandError(message) from exc

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        preview = result.stdout.strip().replace("\n", " ")[:200]
        raise GhCommandError(
            f"gh command returned non-JSON output: {' '.join(cmd)}: {preview!r}"
        ) from exc


def fetch_inline_review_comments(repo: str, pr_number: int) -> list[dict]:
    """Fetch inline review comments via REST API (not available via gh pr view)."""
    return run_json(
        ["gh", "api", f"repos/{repo}/pulls/{pr_number}/comments", "--paginate"]
    )


def collect_surface(repo: str, pr_number: int) -> dict[str, object]:
    payload = run_json(
        ["gh", "pr", "view", str(pr_number), "-R", repo, "--json", PR_VIEW_FIELDS]
    )
    if not isinstance(payload, dict):
        raise GhCommandError("gh pr view returned a non-object payload")

    comments = payload.get("comments")
    reviews = payload.get("reviews")
    files = payload.get("files")
    if not isinstance(comments, list) or not isinstance(reviews, list) or not isinstance(files, list):
        raise GhCommandError("payload missing comments, reviews, or files arrays")

    review_comments = fetch_inline_review_comments(repo, pr_number)

    cerberus_comments = [
        c for c in comments
        if isinstance(c, dict) and "<!-- cerberus:verdict -->" in str(c.get("body", ""))
    ]

    all_collections = (comments, reviews, review_comments)

    return {
        "repo": repo,
        "pr_number": payload.get("number"),
        "title": payload.get("title"),
        "url": payload.get("url"),
        "body": payload.get("body"),
        "files": files,
        "comments": comments,
        "reviews": reviews,
        "review_comments": review_comments,
        "cerberus_comments": cerberus_comments,
        "external_authors": sorted(
            {
                str(login)
                for collection in all_collections
                for item in collection
                if isinstance(item, dict)
                for login in [(item.get("author") or item.get("user") or {}).get("login")]
                if login
            }
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect one PR review surface for reviewer delta triage.")
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--pr", required=True, type=int, help="pull request number")
    parser.add_argument("--out", help="optional output JSON path")
    args = parser.parse_args(argv)

    if args.pr < 1:
        parser.error("--pr must be >= 1")

    try:
        surface = collect_surface(args.repo, args.pr)
    except GhCommandError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # Print channel counts to stderr so the caller sees what was collected
    print(
        f"Collected: {len(surface['comments'])} comments, "
        f"{len(surface['reviews'])} reviews, "
        f"{len(surface['review_comments'])} inline review comments, "
        f"{len(surface['external_authors'])} authors",
        file=sys.stderr,
    )

    text = json.dumps(surface, indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(args.out)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
