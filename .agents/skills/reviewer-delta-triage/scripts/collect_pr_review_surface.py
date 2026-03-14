#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys


class GhCommandError(RuntimeError):
    """Raised when a gh CLI command fails or returns non-JSON output."""


FIELDS = "number,title,url,body,files,comments,reviews"


def run_json(cmd: list[str]) -> object:
    try:
        result = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            check=True,
        )
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


def collect_surface(repo: str, pr_number: int) -> dict[str, object]:
    payload = run_json(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "-R",
            repo,
            "--json",
            FIELDS,
        ]
    )
    if not isinstance(payload, dict):
        raise GhCommandError("gh pr view returned a non-object payload")

    comments = payload.get("comments")
    reviews = payload.get("reviews")
    files = payload.get("files")
    if not isinstance(comments, list) or not isinstance(reviews, list) or not isinstance(files, list):
        raise GhCommandError("gh pr view payload is missing comments, reviews, or files arrays")

    cerberus_comments = [
        comment
        for comment in comments
        if isinstance(comment, dict) and "<!-- cerberus:verdict -->" in str(comment.get("body", ""))
    ]

    return {
        "repo": repo,
        "pr_number": payload.get("number"),
        "title": payload.get("title"),
        "url": payload.get("url"),
        "body": payload.get("body"),
        "files": files,
        "comments": comments,
        "reviews": reviews,
        "cerberus_comments": cerberus_comments,
        "external_authors": sorted(
            {
                str(author.get("login"))
                for collection in (comments, reviews)
                for item in collection
                if isinstance(item, dict)
                for author in [item.get("author")]
                if isinstance(author, dict) and author.get("login")
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
        payload = collect_surface(args.repo, args.pr)
    except GhCommandError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(args.out)
        return 0

    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
