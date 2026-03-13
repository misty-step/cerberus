"""GitHub transport boundary for Cerberus review execution paths."""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import tempfile
import time
from typing import NoReturn


class GitHubPermissionError(Exception):
    """Token lacks permission for the requested GitHub write."""


class GitHubAuthError(Exception):
    """GitHub authentication failed for the requested operation."""


class TransientGitHubError(Exception):
    """GitHub API returned a transient error after retries."""


class GitHubTimeoutError(Exception):
    """GitHub command timed out."""


DEFAULT_GH_TIMEOUT = 20
PR_CONTEXT_FIELDS = "title,author,headRefName,baseRefName,body"
RATE_LIMIT_MARKERS = ("rate limit exceeded", "secondary rate limit", "abuse detection")


def classify_gh_failure(stderr: str) -> str:
    """Classify GitHub CLI stderr into a small stable taxonomy."""

    lower_stderr = stderr.lower()
    if any(marker in lower_stderr for marker in RATE_LIMIT_MARKERS):
        return "transient"

    http_401_markers = ("http 401", "(http 401)", "401 unauthorized", "status 401")
    http_403_markers = ("http 403", "(http 403)", "403 forbidden", "status 403")
    auth_markers = (
        "bad credentials",
        "authentication failed",
        "invalid api key",
        "incorrect_api_key",
        "not authenticated",
    )
    if any(marker in lower_stderr for marker in http_401_markers) or any(
        marker in lower_stderr for marker in auth_markers
    ):
        return "auth"
    permission_markers = ("forbidden", "resource not accessible", "permission denied")
    if any(marker in lower_stderr for marker in http_403_markers) or any(
        marker in lower_stderr for marker in permission_markers
    ) or (
        "missing" in lower_stderr and "permission" in lower_stderr
    ):
        return "permissions"
    if is_transient_error(stderr):
        return "transient"
    return "other"


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


def _run_gh_capture(args: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    """Run gh and capture stdout/stderr for bootstrap-style flows."""

    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _raise_for_bootstrap_failure(
    result: subprocess.CompletedProcess[str],
    *,
    permission_message: str,
) -> NoReturn:
    """Raise a deterministic exception for a bootstrap fetch failure."""

    kind = classify_gh_failure(result.stderr or "")
    if kind == "auth":
        raise GitHubAuthError((result.stderr or "").strip() or "GitHub authentication failed")
    if kind == "permissions":
        raise GitHubPermissionError(permission_message)
    if kind == "transient":
        raise TransientGitHubError((result.stderr or "").strip() or "GitHub transient failure")
    raise subprocess.CalledProcessError(
        result.returncode,
        result.args,
        result.stdout,
        result.stderr,
    )


def fetch_issue_comments(
    repo: str,
    number: int,
    *,
    per_page: int = 100,
    max_pages: int | None = 20,
    stop_on_marker: str | None = None,
) -> list[dict]:
    """Fetch issue comments for a PR or issue using the shared transport."""

    comments: list[dict] = []
    page = 1
    while max_pages is None or page <= max_pages:
        endpoint = f"repos/{repo}/issues/{number}/comments?per_page={per_page}&page={page}"
        payload = gh_json(["api", endpoint], timeout=DEFAULT_GH_TIMEOUT)
        if not isinstance(payload, list):
            raise ValueError(f"unexpected comments payload type: {type(payload).__name__}")
        if not payload:
            break
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            comments.append(entry)
            if stop_on_marker is not None and stop_on_marker in str(entry.get("body", "")):
                return comments
        if len(payload) < per_page:
            break
        page += 1
    return comments


def fetch_pr_diff(repo: str, pr_number: int, *, timeout: int = DEFAULT_GH_TIMEOUT) -> str:
    """Fetch a pull-request diff without assuming a checked-out repository."""

    try:
        result = _run_gh_capture(["pr", "diff", str(pr_number), "--repo", repo], timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise GitHubTimeoutError(f"gh pr diff timed out after {timeout}s") from exc
    if result.returncode == 0:
        return result.stdout
    _raise_for_bootstrap_failure(
        result,
        permission_message=(
            "Unable to read pull request diff: token lacks pull-requests: read permission.\n"
            "Add this to your workflow:\n"
            "permissions:\n"
            "  contents: read\n"
            "  pull-requests: read"
        ),
    )


def fetch_pr_context(
    repo: str,
    pr_number: int,
    *,
    timeout: int = DEFAULT_GH_TIMEOUT,
    max_retries: int = 3,
) -> dict:
    """Fetch core pull-request metadata for bootstrap scaffolding."""

    for attempt in range(1, max_retries + 1):
        try:
            result = _run_gh_capture(
                [
                    "pr",
                    "view",
                    str(pr_number),
                    "--repo",
                    repo,
                    "--json",
                    PR_CONTEXT_FIELDS,
                ],
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitHubTimeoutError(f"gh pr view timed out after {timeout}s") from exc

        if result.returncode == 0:
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON from gh pr view: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError("invalid PR context payload: expected object")
            missing_fields = [
                field for field in PR_CONTEXT_FIELDS.split(",") if field not in payload
            ]
            if missing_fields:
                raise ValueError(
                    "invalid PR context payload: missing fields "
                    + ", ".join(missing_fields)
                )
            return payload

        if classify_gh_failure(result.stderr or "") == "auth" and attempt < max_retries:
            time.sleep(attempt * 2)
            continue

        _raise_for_bootstrap_failure(
            result,
            permission_message=(
                "Unable to read pull request context: token lacks pull-requests: read permission.\n"
                "Add this to your workflow:\n"
                "permissions:\n"
                "  contents: read\n"
                "  pull-requests: read"
            ),
        )

    raise RuntimeError("fetch_pr_context retry loop exited unexpectedly")


def create_issue_comment(*, repo: str, number: int, body_file: str) -> subprocess.CompletedProcess[str]:
    """Create an issue or PR comment using the shared transport."""

    return run_gh(
        ["api", f"repos/{repo}/issues/{number}/comments", "-F", f"body=@{body_file}"],
        timeout=DEFAULT_GH_TIMEOUT,
    )


def update_issue_comment(
    *,
    repo: str,
    comment_id: int,
    body_file: str,
) -> subprocess.CompletedProcess[str]:
    """Update an existing issue or PR comment using the shared transport."""

    return run_gh(
        [
            "api",
            f"repos/{repo}/issues/comments/{comment_id}",
            "-X",
            "PATCH",
            "-F",
            f"body=@{body_file}",
        ],
        timeout=DEFAULT_GH_TIMEOUT,
    )


def list_pr_reviews(repo: str, pr_number: int) -> list[dict]:
    """List reviews for a pull request."""

    payload = gh_json(
        [
            "api",
            "--paginate",
            "--slurp",
            f"repos/{repo}/pulls/{pr_number}/reviews?per_page=100",
        ],
        timeout=DEFAULT_GH_TIMEOUT,
    )
    if not isinstance(payload, list):
        return []

    return [
        item
        for page in payload
        if isinstance(page, list)
        for item in page
        if isinstance(item, dict)
    ]


def list_pr_files(repo: str, pr_number: int) -> list[dict]:
    """List changed files for a pull request."""

    payload = gh_json(
        [
            "api",
            "--paginate",
            "--slurp",
            f"repos/{repo}/pulls/{pr_number}/files?per_page=100",
        ],
        timeout=DEFAULT_GH_TIMEOUT,
    )
    if not isinstance(payload, list):
        return []

    return [
        item
        for page in payload
        if isinstance(page, list)
        for item in page
        if isinstance(item, dict)
    ]


def create_pr_review(
    *,
    repo: str,
    pr_number: int,
    commit_id: str,
    body: str,
    comments: list[dict[str, object]],
) -> dict:
    """Create a single pull-request review with optional inline comments."""

    payload: dict[str, object] = {
        "event": "COMMENT",
        "commit_id": commit_id,
        "body": body,
    }
    if comments:
        payload["comments"] = comments

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        json.dump(payload, handle)
        handle.flush()
        payload_path = handle.name

    try:
        result = run_gh(
            [
                "api",
                "-X",
                "POST",
                f"repos/{repo}/pulls/{pr_number}/reviews",
                "--input",
                payload_path,
            ],
            timeout=DEFAULT_GH_TIMEOUT,
        )
    finally:
        try:
            os.unlink(payload_path)
        except FileNotFoundError:
            pass
    data = json.loads(result.stdout or "{}")
    return data if isinstance(data, dict) else {}
