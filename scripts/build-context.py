#!/usr/bin/env python3
"""Build a context bundle for PR review.

Creates a structured context bundle directory containing:
- metadata.json: PR number, title, author, labels, etc.
- diff.patch: The actual diff (separate file, not inline)
- files.json: List of changed files with paths
- comments.json: Existing review comments (if any)

Usage:
    python3 build-context.py <output_dir> [pr_context_json] [diff_file]

Environment variables (fallback if args not provided):
    GH_PR_CONTEXT: Path to PR context JSON file
    GH_DIFF_FILE: Path to diff file
    GH_PR_NUMBER: PR number (for comments fetch)
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Build context bundle for PR review"
    )
    parser.add_argument(
        "output_dir",
        help="Output directory for context bundle"
    )
    parser.add_argument(
        "pr_context_json",
        nargs="?",
        help="Path to PR context JSON file (optional, uses env fallback)"
    )
    parser.add_argument(
        "diff_file",
        nargs="?",
        help="Path to diff file (optional, uses env fallback)"
    )
    return parser.parse_args()


def read_pr_context(pr_context_path: str | None) -> dict[str, Any]:
    """Read PR context from JSON file or environment."""
    # Try argument first
    if pr_context_path and Path(pr_context_path).exists():
        return json.loads(Path(pr_context_path).read_text())

    # Try environment variable
    env_path = os.environ.get("GH_PR_CONTEXT", "")
    if env_path and Path(env_path).exists():
        return json.loads(Path(env_path).read_text())

    # Build from individual env vars
    author = os.environ.get("GH_PR_AUTHOR", "")
    return {
        "title": os.environ.get("GH_PR_TITLE", ""),
        "author": {"login": author} if author else {},
        "headRefName": os.environ.get("GH_HEAD_BRANCH", ""),
        "baseRefName": os.environ.get("GH_BASE_BRANCH", ""),
        "body": os.environ.get("GH_PR_BODY", ""),
    }


def read_diff(diff_path: str | None) -> str:
    """Read diff from file or environment."""
    # Try argument first
    if diff_path and Path(diff_path).exists():
        return Path(diff_path).read_text(errors="ignore")

    # Try environment variable
    env_path = os.environ.get("GH_DIFF_FILE", "")
    if env_path and Path(env_path).exists():
        return Path(env_path).read_text(errors="ignore")

    # Try raw env var
    return os.environ.get("GH_DIFF", "")


def extract_changed_files(diff_text: str) -> list[dict[str, str]]:
    """Extract list of changed files from diff."""
    files = []
    seen = set()

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                # Extract path from "a/path" or "b/path"
                path = parts[2]
                if path.startswith("a/"):
                    path = path[2:]
                if path and path not in seen:
                    seen.add(path)
                    files.append({
                        "path": path,
                        "status": "modified"  # Default, could be enhanced
                    })

    return files


def fetch_comments(pr_number: str | None) -> list[dict[str, Any]]:
    """Fetch existing review comments for the PR."""
    if not pr_number:
        pr_number = os.environ.get("GH_PR_NUMBER", "")

    if not pr_number:
        return []

    try:
        result = subprocess.run(
            ["gh", "pr", "view", pr_number, "--json", "comments"],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("comments", [])
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass

    return []


def build_metadata(pr_context: dict[str, Any]) -> dict[str, Any]:
    """Build metadata.json content from PR context."""
    author = pr_context.get("author", {})
    if isinstance(author, dict):
        author_login = author.get("login", "")
    else:
        author_login = str(author)

    return {
        "pr_number": os.environ.get("GH_PR_NUMBER", ""),
        "title": pr_context.get("title", ""),
        "author": author_login,
        "head_branch": pr_context.get("headRefName", ""),
        "base_branch": pr_context.get("baseRefName", ""),
        "description": pr_context.get("body", ""),
        "labels": pr_context.get("labels", []),
        "draft": pr_context.get("isDraft", False),
        "created_at": pr_context.get("createdAt", ""),
        "updated_at": pr_context.get("updatedAt", ""),
    }


def build_context_bundle(
    output_dir: Path,
    pr_context: dict[str, Any],
    diff_text: str,
    comments: list[dict[str, Any]]
) -> None:
    """Build and write the context bundle to output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write metadata.json
    metadata = build_metadata(pr_context)
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2)
    )

    # Write diff.patch
    (output_dir / "diff.patch").write_text(diff_text)

    # Write files.json
    files = extract_changed_files(diff_text)
    (output_dir / "files.json").write_text(
        json.dumps({"files": files}, indent=2)
    )

    # Write comments.json
    (output_dir / "comments.json").write_text(
        json.dumps({"comments": comments}, indent=2)
    )

    # Write bundle info
    bundle_info = {
        "version": "1.0",
        "created_at": __import__('datetime').datetime.utcnow().isoformat(),
        "files": ["metadata.json", "diff.patch", "files.json", "comments.json"]
    }
    (output_dir / "bundle.json").write_text(
        json.dumps(bundle_info, indent=2)
    )


def main() -> int:
    """Main entry point."""
    args = parse_args()

    output_dir = Path(args.output_dir)

    # Read inputs
    pr_context = read_pr_context(args.pr_context_json)
    diff_text = read_diff(args.diff_file)

    # Fetch comments if gh CLI is available
    comments = fetch_comments(pr_context.get("number"))

    # Build bundle
    build_context_bundle(output_dir, pr_context, diff_text, comments)

    # Output info
    print(f"Context bundle created: {output_dir}")
    print(f"  - metadata.json: PR metadata")
    print(f"  - diff.patch: {len(diff_text)} bytes")
    print(f"  - files.json: {len(extract_changed_files(diff_text))} files")
    print(f"  - comments.json: {len(comments)} comments")

    # Also output path for GitHub Actions
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"context-bundle-path={output_dir}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
