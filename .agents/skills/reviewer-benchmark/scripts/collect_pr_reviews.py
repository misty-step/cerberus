#!/usr/bin/env python3

import argparse
from datetime import date
import json
import subprocess
import sys


class GhCommandError(RuntimeError):
    """Raised when a gh CLI command fails or returns non-JSON output."""


def run_json(cmd):
    """Run a gh command and parse its stdout as JSON."""

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
    """Return explicit repos or the non-archived repos for an org."""

    if explicit_repos:
        return list(dict.fromkeys(explicit_repos))
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
    """Collect recent pull requests and review payloads for a repo."""

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


def validate_since(value):
    """Require a strict ISO calendar date to keep gh search syntax deterministic."""

    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--since must be a valid YYYY-MM-DD date") from exc
    return value


def build_repo_result(*, pull_requests=None, error=None, truncated=False):
    """Keep the output schema consistent for successful and failed repos."""

    return {
        "pull_requests": pull_requests or [],
        "error": error,
        "truncated": truncated,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Collect recent PR review corpus with gh CLI.")
    parser.add_argument("--org", required=True, help="GitHub organization")
    parser.add_argument(
        "--since",
        required=True,
        type=validate_since,
        help="YYYY-MM-DD lower bound for updated PRs",
    )
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
    repo_listing_truncated = False

    for idx, repo in enumerate(repos, start=1):
        try:
            pull_requests = collect_repo(repo, args.since, args.limit)
        except GhCommandError as exc:
            result[repo] = build_repo_result(error=str(exc))
        else:
            repo_truncated = len(pull_requests) == args.limit
            result[repo] = build_repo_result(
                pull_requests=pull_requests,
                truncated=repo_truncated,
            )
            if repo_truncated:
                print(
                    f"Warning: {repo} hit --limit={args.limit}; rerun with a higher value to avoid truncation.",
                    file=sys.stderr,
                )
        if idx % 10 == 0 or idx == len(repos):
            print(f"{idx}/{len(repos)} repos collected", file=sys.stderr)

    try:
        with open(args.out, "w", encoding="utf-8") as fh:
            if not args.repo and len(repos) == args.repo_limit:
                repo_listing_truncated = True
            json.dump(
                {
                    "org": args.org,
                    "since": args.since,
                    "repo_limit": args.repo_limit,
                    "pull_request_limit": args.limit,
                    "repo_listing_truncated": repo_listing_truncated,
                    "repos": result,
                },
                fh,
            )
    except OSError as exc:
        print(f"Failed to write output file '{args.out}': {exc}", file=sys.stderr)
        return 1

    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
