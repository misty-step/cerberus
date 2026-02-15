#!/usr/bin/env python3
"""Post council output as a PR review with inline comments.

This is additive: the verdict action still posts the council issue comment
(used by triage). This script posts a single PR review for the same SHA with
up to 30 inline comments anchored to diff `position`s.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from lib.diff_positions import build_newline_to_position
from lib.findings import best_text, format_reviewer_list, norm_key
from lib.github import (
    CommentPermissionError,
    TransientGitHubError,
    fetch_comments,
    find_comment_url_by_marker,
)
from lib.github_reviews import ReviewComment, create_pr_review, find_review_id_by_marker, list_pr_files, list_pr_reviews
from lib.markdown import severity_icon

MAX_INLINE_COMMENTS = 30
MAX_INLINE_PER_FILE = 3

INLINE_SEVERITIES = {"critical", "major"}

_SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "info": 3}


def fail(message: str, code: int = 2) -> None:
    print(f"post-council-review: {message}", file=sys.stderr)
    sys.exit(code)


def warn(message: str) -> None:
    print(f"::warning::{message}", file=sys.stderr)


def notice(message: str) -> None:
    print(f"::notice::{message}", file=sys.stderr)


def as_int(value: object) -> int | None:
    try:
        i = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return i


def normalize_severity(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if text in _SEVERITY_ORDER else "info"


def normalize_path(path: object) -> str:
    text = str(path or "").strip()
    if text.startswith(("a/", "b/")):
        text = text[2:]
    if text.startswith("./"):
        text = text[2:]
    return text


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        fail(f"unable to read {path}: {exc}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path}: {exc}")
    return data if isinstance(data, dict) else {}


def review_marker(head_sha: str) -> str:
    short = head_sha[:12] if head_sha else "<head-sha>"
    return f"<!-- cerberus:council-review sha={short} -->"


def collect_inline_findings(council: dict) -> list[dict]:
    reviewers = council.get("reviewers")
    if not isinstance(reviewers, list):
        return []

    grouped: dict[tuple[str, int, str, str], dict] = {}
    for reviewer in reviewers:
        if not isinstance(reviewer, dict):
            continue
        rname = str(reviewer.get("reviewer") or reviewer.get("perspective") or "unknown")
        findings = reviewer.get("findings")
        if not isinstance(findings, list):
            continue
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            file = normalize_path(finding.get("file"))
            line = as_int(finding.get("line"))
            if not file or line is None or line <= 0:
                continue
            severity = normalize_severity(finding.get("severity"))
            if severity not in INLINE_SEVERITIES:
                continue
            category = str(finding.get("category") or "").strip() or "uncategorized"
            title = str(finding.get("title") or "").strip() or "Untitled finding"

            key = (file, line, norm_key(category), norm_key(title))
            existing = grouped.get(key)
            if existing is None:
                grouped[key] = {
                    "reviewers": {rname},
                    "severity": severity,
                    "category": category,
                    "file": file,
                    "line": line,
                    "title": title,
                    "description": str(finding.get("description") or "").strip(),
                    "suggestion": str(finding.get("suggestion") or "").strip(),
                    "evidence": str(finding.get("evidence") or "").strip(),
                }
                continue

            existing["reviewers"].add(rname)
            if _SEVERITY_ORDER[severity] < _SEVERITY_ORDER[existing.get("severity")]:
                existing["severity"] = severity
            existing["description"] = best_text(existing.get("description", ""), finding.get("description"))
            existing["suggestion"] = best_text(existing.get("suggestion", ""), finding.get("suggestion"))
            existing["evidence"] = best_text(existing.get("evidence", ""), finding.get("evidence"))

    out: list[dict] = []
    for item in grouped.values():
        reviewers = sorted(str(r or "").strip() for r in item.get("reviewers", set()) if str(r or "").strip())
        item["reviewers"] = reviewers
        out.append(item)
    return out


def truncate(text: str, *, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def render_inline_comment(finding: dict) -> str:
    sev = normalize_severity(finding.get("severity"))
    icon = severity_icon(sev)
    title = truncate(str(finding.get("title") or "Untitled finding"), max_len=200)
    category = truncate(str(finding.get("category") or "uncategorized"), max_len=80)
    reviewer = truncate(format_reviewer_list(finding.get("reviewers")), max_len=60)
    description = truncate(str(finding.get("description") or ""), max_len=700)
    suggestion = truncate(str(finding.get("suggestion") or ""), max_len=700)
    evidence = truncate(str(finding.get("evidence") or ""), max_len=900)

    lines = [f"{icon} **{title}** (`{category}`) ({reviewer})"]
    if description:
        lines.append("")
        lines.append(description)
    if suggestion:
        lines.append("")
        lines.append(f"Suggestion: {suggestion}")
    if evidence:
        lines.append("")
        lines.append("<details>")
        lines.append("<summary>Evidence</summary>")
        lines.append("")
        lines.append("```text")
        lines.extend(evidence.splitlines())
        lines.append("```")
        lines.append("")
        lines.append("</details>")
    return "\n".join(lines).strip() + "\n"


def build_patch_index(repo: str, pr_number: int) -> dict[str, tuple[str, dict[int, int]]]:
    """Map normalized path -> (canonical filename, newline->position map)."""
    files = list_pr_files(repo, pr_number)
    index: dict[str, tuple[str, dict[int, int]]] = {}
    for item in files:
        filename = item.get("filename")
        if not isinstance(filename, str) or not filename.strip():
            continue
        patch = item.get("patch")
        if not isinstance(patch, str) or not patch.strip():
            continue
        mapping = build_newline_to_position(patch)
        canonical = filename.strip()
        index[normalize_path(canonical)] = (canonical, mapping)
        prev = item.get("previous_filename")
        if isinstance(prev, str) and prev.strip():
            index[normalize_path(prev)] = (canonical, mapping)
    return index


def main() -> None:
    p = argparse.ArgumentParser(description="Post Cerberus council as a PR review with inline comments.")
    p.add_argument("--repo", required=True, help="owner/repo")
    p.add_argument("--pr", type=int, required=True, help="PR number")
    p.add_argument("--head-sha", default="", help="Head SHA (default: env GH_HEAD_SHA)")
    p.add_argument(
        "--council-json",
        default="/tmp/council-verdict.json",
        help="Path to council verdict JSON.",
    )
    p.add_argument(
        "--body-file",
        default="/tmp/council-comment.md",
        help="Council markdown body file (unused; council issue comment is canonical).",
    )
    args = p.parse_args()

    head_sha = (args.head_sha or os.environ.get("GH_HEAD_SHA") or "").strip()
    if not head_sha:
        fail("missing head sha (set --head-sha or GH_HEAD_SHA)")

    marker = review_marker(head_sha)

    try:
        reviews = list_pr_reviews(args.repo, args.pr)
        if find_review_id_by_marker(reviews, marker) is not None:
            notice(f"Council review already posted for sha={head_sha[:12]} (marker match). Skipping.")
            return

        council = read_json(Path(args.council_json))

        findings = collect_inline_findings(council)
        eligible = len(findings)
        if eligible == 0:
            notice("No critical/major findings eligible for inline comments. Skipping PR review.")
            return

        patch_index = build_patch_index(args.repo, args.pr)

        mapped: list[tuple[ReviewComment, tuple[int, str, int, str]]] = []
        for finding in findings:
            path_key = normalize_path(finding.get("file"))
            line = as_int(finding.get("line"))
            if not path_key or line is None or line <= 0:
                continue
            entry = patch_index.get(path_key)
            if not entry:
                continue
            canonical_path, line_map = entry
            position = line_map.get(line)
            if not position:
                continue

            comment = ReviewComment(
                path=canonical_path,
                position=position,
                body=render_inline_comment(finding),
            )
            sort_key = (
                _SEVERITY_ORDER[normalize_severity(finding.get("severity"))],
                canonical_path,
                line,
                str(finding.get("title") or ""),
            )
            mapped.append((comment, sort_key))

        mapped.sort(key=lambda item: item[1])
        inline: list[ReviewComment] = []
        per_file: dict[str, int] = {}
        for (comment, _k) in mapped:
            if len(inline) >= MAX_INLINE_COMMENTS:
                break
            count = per_file.get(comment.path, 0)
            if count >= MAX_INLINE_PER_FILE:
                continue
            inline.append(comment)
            per_file[comment.path] = count + 1

        anchorable = len(mapped)
        posted = len(inline)
        omitted = max(0, anchorable - posted)
        unanchored = max(0, eligible - anchorable)
        limit_note = ""
        if omitted or unanchored:
            bits: list[str] = []
            if omitted:
                bits.append(f"top {posted}/{anchorable} anchored (cap {MAX_INLINE_COMMENTS}, {MAX_INLINE_PER_FILE}/file)")
            if unanchored:
                bits.append(f"{unanchored} unanchored")
            limit_note = f" ({'; '.join(bits)})"

        if posted == 0:
            notice(f"No inline comments could be anchored to the diff{limit_note}. Skipping PR review.")
            return

        council_comment_url = ""
        try:
            # Use stop_on_marker for early exit - we only need to find the council comment
            comments = fetch_comments(args.repo, args.pr, stop_on_marker="<!-- cerberus:council -->")
            council_comment_url = find_comment_url_by_marker(comments, "<!-- cerberus:council -->") or ""
        except (CommentPermissionError, TransientGitHubError, subprocess.CalledProcessError) as exc:
            warn(f"Unable to fetch council comment URL: {exc}")
            council_comment_url = ""

        council_verdict = str(council.get("verdict") or "").strip().upper() or "UNKNOWN"
        council_summary = str(council.get("summary") or "").strip()
        sha_short = head_sha[:12]

        link_line = f"[council report]({council_comment_url})" if council_comment_url else "council report (timeline)"
        review_body = "\n".join(
            [
                marker,
                f"**Cerberus inline comments** for `{sha_short}`",
                "",
                f"- Inline comments posted: {posted}/{eligible}{limit_note}",
                f"- Canonical report: {link_line}",
                f"- Council verdict: `{council_verdict}`" + (f" ({council_summary})" if council_summary else ""),
                "",
            ]
        )

        try:
            create_pr_review(
                repo=args.repo,
                pr_number=args.pr,
                commit_id=head_sha,
                body=review_body,
                comments=inline,
            )
            notice(f"Posted council PR review for sha={head_sha[:12]} with {posted} inline comments.")
        except subprocess.CalledProcessError as exc:
            warn(f"Review with inline comments failed; skipping PR review. ({exc.stderr or exc})")

    except CommentPermissionError as exc:
        warn(str(exc))
    except TransientGitHubError as exc:
        warn(str(exc))
    except Exception as exc:  # don't block verdict on UX extras
        warn(f"Unable to post council PR review: {exc}")


if __name__ == "__main__":
    main()
