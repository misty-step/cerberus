"""Markdown helpers for Cerberus PR comments.

Keep surface area small: link formatting + severity badges + <details> blocks.
"""

from __future__ import annotations

import os
from urllib.parse import quote

_SEVERITY_ICON = {
    "critical": "🔴",
    "major": "🟠",
    "minor": "🟡",
    "info": "🔵",
}


def severity_icon(severity: str | None) -> str:
    """Severity icon."""
    text = str(severity or "").strip().lower()
    return _SEVERITY_ICON.get(text, _SEVERITY_ICON["info"])


def repo_context(
    *,
    server: str | None = None,
    repo: str | None = None,
    sha: str | None = None,
) -> tuple[str, str, str]:
    """Resolve GitHub context used for blob links."""
    resolved_server = (server or os.environ.get("GITHUB_SERVER_URL") or "https://github.com").rstrip(
        "/"
    )
    resolved_repo = (repo or os.environ.get("GITHUB_REPOSITORY") or "").strip()
    resolved_sha = (sha or os.environ.get("GH_HEAD_SHA") or "").strip()
    return resolved_server, resolved_repo, resolved_sha


def blob_url(
    path: str,
    *,
    server: str,
    repo: str,
    sha: str,
    line: int | None = None,
) -> str | None:
    """Blob url."""
    server = (server or "").rstrip("/")
    repo = (repo or "").strip()
    sha = (sha or "").strip()
    path = (path or "").strip()

    if not (server and repo and sha and path):
        return None
    url = f"{server}/{repo}/blob/{sha}/{quote(path, safe='/')}"
    if line is not None and line > 0:
        url += f"#L{line}"
    return url


def _location_label(path: str, line: int | None) -> str:
    path = (path or "").strip()
    if not path:
        return ""
    if line is not None and line > 0:
        return f"{path}:{line}"
    return path


def location_link(
    path: str,
    line: int | None,
    *,
    server: str,
    repo: str,
    sha: str,
    missing_label: str = "unknown",
) -> str:
    """Location link."""
    path = (path or "").strip()
    if not path:
        return f"`{missing_label}`"

    # Some fallback verdicts use "N/A"; display but don't link.
    if path.upper() == "N/A":
        return "`N/A`"

    label = _location_label(path, line)
    url = blob_url(path, server=server, repo=repo, sha=sha, line=line)
    if not url:
        return f"`{label}`"
    return f"[`{label}`]({url})"


def details_block(
    body_lines: list[str],
    *,
    summary: str = "Details",
    indent: str = "  ",
) -> list[str]:
    """Details block."""
    if not body_lines:
        return []
    lines = [
        f"{indent}<details>",
        f"{indent}<summary>{summary}</summary>",
        "",
    ]
    for ln in body_lines:
        if ln:
            lines.append(f"{indent}{ln}")
        else:
            lines.append("")
    lines.extend(["", f"{indent}</details>"])
    return lines

