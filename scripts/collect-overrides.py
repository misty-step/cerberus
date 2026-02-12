#!/usr/bin/env python3
"""Collect override comments and actor permissions without shell parsing."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4


def run_gh(args: list[str], *, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            result.args,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result


def gh_json(args: list[str], *, timeout: int = 20) -> object:
    result = run_gh(args, timeout=timeout)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON from gh command {args!r}: {exc}") from exc


def fetch_pr_comments(repo: str, pr_number: int, *, per_page: int = 100) -> list[dict]:
    comments: list[dict] = []
    page = 1
    while True:
        endpoint = f"repos/{repo}/issues/{pr_number}/comments?per_page={per_page}&page={page}"
        payload = gh_json(["api", endpoint], timeout=20)
        if not isinstance(payload, list):
            raise ValueError(f"unexpected comments payload type: {type(payload).__name__}")
        if not payload:
            break
        comments.extend([entry for entry in payload if isinstance(entry, dict)])
        if len(payload) < per_page:
            break
        page += 1
    return comments


def extract_override_comments(comments: list[dict]) -> list[dict[str, str]]:
    collected: list[dict[str, str]] = []
    for comment in comments:
        body = comment.get("body")
        if not isinstance(body, str) or not body.startswith("/council override"):
            continue
        user = comment.get("user")
        actor = ""
        if isinstance(user, dict):
            actor = str(user.get("login") or "")
        collected.append({"actor": actor, "body": body})
    return collected


def fetch_actor_permissions(repo: str, actors: list[str]) -> dict[str, str]:
    permissions: dict[str, str] = {}
    for actor in sorted(set(actors)):
        if not actor:
            continue
        endpoint = f"repos/{repo}/collaborators/{actor}/permission"
        try:
            payload = gh_json(["api", endpoint], timeout=10)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
            permissions[actor] = ""
            continue
        permission = ""
        if isinstance(payload, dict):
            raw_permission = payload.get("permission")
            if isinstance(raw_permission, str):
                permission = raw_permission
        permissions[actor] = permission
    return permissions


def collect_override_data(repo: str, pr_number: int) -> tuple[list[dict[str, str]], dict[str, str]]:
    comments = fetch_pr_comments(repo, pr_number)
    overrides = extract_override_comments(comments)
    actors = [entry.get("actor", "") for entry in overrides]
    permissions = fetch_actor_permissions(repo, actors) if actors else {}
    return overrides, permissions


def append_multiline_output(path: Path, key: str, value: str) -> None:
    delimiter = f"CERBERUS_{key.upper()}_{uuid4().hex}"
    while delimiter in value:
        delimiter = f"CERBERUS_{key.upper()}_{uuid4().hex}"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"{key}<<{delimiter}\n")
        fh.write(value)
        if not value.endswith("\n"):
            fh.write("\n")
        fh.write(f"{delimiter}\n")


def write_github_outputs(output_path: Path, overrides: list[dict[str, str]], actor_permissions: dict[str, str]) -> None:
    append_multiline_output(output_path, "overrides", json.dumps(overrides, separators=(",", ":")))
    append_multiline_output(
        output_path,
        "actor_permissions",
        json.dumps(actor_permissions, separators=(",", ":")),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect council override comments and actor permissions.",
    )
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--pr", type=int, required=True, help="pull request number")
    parser.add_argument(
        "--github-output",
        default="",
        help="Path to GITHUB_OUTPUT file. If omitted, writes JSON to stdout.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    overrides: list[dict[str, str]] = []
    actor_permissions: dict[str, str] = {}

    try:
        overrides, actor_permissions = collect_override_data(args.repo, args.pr)
    except Exception as exc:
        print(f"::warning::Failed to fetch override comments: {exc}", file=sys.stderr)

    if args.github_output:
        output_path = Path(args.github_output)
        write_github_outputs(output_path, overrides, actor_permissions)
        return

    print(
        json.dumps(
            {
                "overrides": overrides,
                "actor_permissions": actor_permissions,
            },
            indent=2,
            sort_keys=False,
        )
    )


if __name__ == "__main__":
    main()
