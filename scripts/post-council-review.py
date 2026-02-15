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
from lib.github import CommentPermissionError, TransientGitHubError
from lib.github_reviews import ReviewComment, create_pr_review, find_review_id_by_marker, list_pr_files, list_pr_reviews
from lib.markdown import severity_icon

MAX_INLINE_COMMENTS = 30

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


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"unable to read {path}: {exc}")


def review_marker(head_sha: str) -> str:
    short = head_sha[:12] if head_sha else "<head-sha>"
    return f"<!-- cerberus:council-review sha={short} -->"


def collect_inline_findings(council: dict) -> list[dict]:
    reviewers = council.get("reviewers")
    if not isinstance(reviewers, list):
        return []

    out: list[dict] = []
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
            out.append(
                {
                    "reviewer": rname,
                    "severity": normalize_severity(finding.get("severity")),
                    "category": str(finding.get("category") or "").strip() or "uncategorized",
                    "file": file,
                    "line": line,
                    "title": str(finding.get("title") or "").strip() or "Untitled finding",
                    "description": str(finding.get("description") or "").strip(),
                    "suggestion": str(finding.get("suggestion") or "").strip(),
                    "evidence": str(finding.get("evidence") or "").strip(),
                }
            )
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
    reviewer = truncate(str(finding.get("reviewer") or "unknown"), max_len=40)
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
        help="Council markdown body file (used as review body).",
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
        council_body = read_text(Path(args.body_file)).strip()

        findings = collect_inline_findings(council)
        patch_index = build_patch_index(args.repo, args.pr)

        mapped: list[tuple[ReviewComment, tuple[int, str, int, str, str]]] = []
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
                str(finding.get("reviewer") or ""),
                str(finding.get("title") or ""),
            )
            mapped.append((comment, sort_key))

        mapped.sort(key=lambda item: item[1])
        inline = [c for (c, _k) in mapped[:MAX_INLINE_COMMENTS]]

        eligible = len(findings)
        posted = len(inline)
        omitted = max(0, eligible - posted)
        limit_note = ""
        if omitted:
            limit_note = f" (top {posted}/{eligible}; GitHub cap {MAX_INLINE_COMMENTS})"

        review_body = "\n".join(
            [
                marker,
                f"> Inline comments posted: {posted}/{eligible}{limit_note}. Full details also in council issue comment.",
                "",
                council_body,
                "",
            ]
        ).strip() + "\n"

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
            # If the review rejects inline comments (bad positions), retry with body-only.
            if inline:
                warn(f"Review with inline comments failed; retrying body-only. ({exc.stderr or exc})")
                create_pr_review(
                    repo=args.repo,
                    pr_number=args.pr,
                    commit_id=head_sha,
                    body=review_body,
                    comments=[],
                )
                notice(f"Posted council PR review (body-only) for sha={head_sha[:12]}.")
            else:
                raise

    except CommentPermissionError as exc:
        warn(str(exc))
    except TransientGitHubError as exc:
        warn(str(exc))
    except Exception as exc:  # don't block verdict on UX extras
        warn(f"Unable to post council PR review: {exc}")


if __name__ == "__main__":
    main()
