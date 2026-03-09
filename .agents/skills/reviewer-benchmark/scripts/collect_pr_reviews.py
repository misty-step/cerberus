#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys


class GhCommandError(RuntimeError):
    """Raised when a gh CLI command fails or returns non-JSON output."""


def run_json(cmd):
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


def list_repos(org, explicit_repos, repo_limit):
    if explicit_repos:
        return explicit_repos
    repos = run_json(
        [
            "gh",
            "repo",
            "list",
            org,
            "--limit",
            str(repo_limit),
            "--json",
            "nameWithOwner,isArchived",
        ]
    )
    return [repo["nameWithOwner"] for repo in repos if not repo.get("isArchived")]


def collect_repo(repo, since, limit):
    cmd = [
        "gh",
        "pr",
        "list",
        "-R",
        repo,
        "--search",
        f"updated:>={since}",
        "--state",
        "all",
        "--limit",
        str(limit),
        "--json",
        "number,title,state,updatedAt,url,author,comments,reviews,reviewDecision",
    ]
    return run_json(cmd)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Collect recent PR review corpus with gh CLI.")
    parser.add_argument("--org", required=True, help="GitHub organization")
    parser.add_argument("--since", required=True, help="YYYY-MM-DD lower bound for updated PRs")
    parser.add_argument("--limit", type=int, default=1000, help="Max PRs per repo")
    parser.add_argument("--repo-limit", type=int, default=1000, help="Max repos to list for an org")
    parser.add_argument("--out", required=True, help="Output JSON path")
    parser.add_argument("--repo", action="append", default=[], help="Optional explicit repo(s)")
    args = parser.parse_args(argv)

    if args.limit < 1:
        parser.error("--limit must be >= 1")
    if args.repo_limit < 1:
        parser.error("--repo-limit must be >= 1")

    try:
        repos = list_repos(args.org, args.repo, args.repo_limit)
    except GhCommandError as exc:
        print(f"Failed to list repos for org '{args.org}': {exc}", file=sys.stderr)
        return 1

    if not args.repo and len(repos) == args.repo_limit:
        print(
            "Warning: repo listing hit --repo-limit; rerun with a higher value to avoid truncation.",
            file=sys.stderr,
        )

    result = {}

    for idx, repo in enumerate(repos, start=1):
        try:
            result[repo] = collect_repo(repo, args.since, args.limit)
        except GhCommandError as exc:
            result[repo] = {"error": str(exc)}
        else:
            if len(result[repo]) == args.limit:
                print(
                    f"Warning: {repo} hit --limit={args.limit}; rerun with a higher value to avoid truncation.",
                    file=sys.stderr,
                )
        if idx % 10 == 0 or idx == len(repos):
            print(f"{idx}/{len(repos)} repos collected", file=sys.stderr)

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh)

    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
