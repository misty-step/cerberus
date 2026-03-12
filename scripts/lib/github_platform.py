"""GitHub transport boundary for Cerberus review execution paths."""

from __future__ import annotations

import json
import random
import subprocess
import sys
import time


class GitHubPermissionError(Exception):
    """Token lacks permission for the requested GitHub write."""


class TransientGitHubError(Exception):
    """GitHub API returned a transient error after retries."""


def is_transient_error(stderr: str) -> bool:
    """Check if stderr looks like a transient GitHub/network failure."""

    transient_codes = ("502", "503", "504")
    lower_stderr = stderr.lower()
    if any(
        f"(http {code})" in lower_stderr or f"http {code}" in lower_stderr
        for code in transient_codes
    ):
        return True

    transient_network_markers = (
        "i/o timeout",
        "connection timed out",
        "connection refused",
        "connection reset",
    )
    return any(marker in lower_stderr for marker in transient_network_markers)


def run_gh(
    args: list[str],
    *,
    check: bool = True,
    max_retries: int = 3,
    base_delay: float = 1.0,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a gh CLI command with shared retry and permission handling."""

    for attempt in range(max_retries):
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

        if result.returncode == 0:
            return result

        stderr = (result.stderr or "").lower()
        if any(s in stderr for s in ("403", "resource not accessible", "insufficient")):
            raise GitHubPermissionError(
                "Unable to post PR comment: token lacks pull-requests: write permission.\n"
                "Add this to your workflow:\n"
                "permissions:\n"
                "  contents: read\n"
                "  pull-requests: write"
            )

        if is_transient_error(result.stderr or ""):
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                print(
                    f"::warning::GitHub API error (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {delay:.1f}s...",
                    file=sys.stderr,
                )
                time.sleep(delay)
                continue
            raise TransientGitHubError(
                f"GitHub API returned transient error after {max_retries} attempts: {result.stderr}"
            )

        if check:
            raise subprocess.CalledProcessError(
                result.returncode, result.args, result.stdout, result.stderr
            )
        return result

    raise RuntimeError("run_gh retry loop exited unexpectedly")


def gh_json(
    args: list[str],
    *,
    timeout: int | None = None,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> object:
    """Run gh and decode a JSON payload."""

    result = run_gh(
        args,
        timeout=timeout,
        max_retries=max_retries,
        base_delay=base_delay,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON from gh command {args!r}: {exc}") from exc


def fetch_issue_comments(
    repo: str,
    number: int,
    *,
    per_page: int = 100,
    max_pages: int = 20,
) -> list[dict]:
    """Fetch issue comments for a PR or issue using the shared transport."""

    comments: list[dict] = []
    for page in range(1, max_pages + 1):
        endpoint = f"repos/{repo}/issues/{number}/comments?per_page={per_page}&page={page}"
        payload = gh_json(["api", endpoint], timeout=20)
        if not isinstance(payload, list):
            raise ValueError(f"unexpected comments payload type: {type(payload).__name__}")
        if not payload:
            break
        comments.extend([entry for entry in payload if isinstance(entry, dict)])
        if len(payload) < per_page:
            break
    return comments
