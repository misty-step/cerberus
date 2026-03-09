#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys


def run_json(cmd):
    raw = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
    return json.loads(raw)


def list_repos(org, explicit_repos):
    if explicit_repos:
        return explicit_repos
    repos = run_json(
        [
            "gh",
            "repo",
            "list",
            org,
            "--limit",
            "100",
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


def main():
    parser = argparse.ArgumentParser(description="Collect recent PR review corpus with gh CLI.")
    parser.add_argument("--org", required=True, help="GitHub organization")
    parser.add_argument("--since", required=True, help="YYYY-MM-DD lower bound for updated PRs")
    parser.add_argument("--limit", type=int, default=30, help="Max PRs per repo")
    parser.add_argument("--out", required=True, help="Output JSON path")
    parser.add_argument("--repo", action="append", default=[], help="Optional explicit repo(s)")
    args = parser.parse_args()

    repos = list_repos(args.org, args.repo)
    result = {}

    for idx, repo in enumerate(repos, start=1):
        try:
            result[repo] = collect_repo(repo, args.since, args.limit)
        except subprocess.CalledProcessError as exc:
            result[repo] = {"error": exc.output}
        if idx % 10 == 0 or idx == len(repos):
            print(f"{idx}/{len(repos)} repos collected", file=sys.stderr)

    with open(args.out, "w") as fh:
        json.dump(result, fh)

    print(args.out)


if __name__ == "__main__":
    main()
