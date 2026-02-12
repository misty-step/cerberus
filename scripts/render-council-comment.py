#!/usr/bin/env python3
"""Render a scannable council PR comment from council verdict JSON."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# GitHub PR comments are silently rejected above 65,536 bytes.
# Budget headroom so the structural markdown always fits.
MAX_COMMENT_SIZE = 60000

VERDICT_ICON = {
    "PASS": "✅",
    "WARN": "⚠️",
    "FAIL": "❌",
    "SKIP": "⏭️",
}

SEVERITY_ORDER = {
    "critical": 0,
    "major": 1,
    "minor": 2,
    "info": 3,
}

VERDICT_ORDER = {
    "FAIL": 0,
    "WARN": 1,
    "SKIP": 2,
    "PASS": 3,
}


def fail(message: str, code: int = 2) -> None:
    print(f"render-council-comment: {message}", file=sys.stderr)
    sys.exit(code)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        fail(f"unable to read {path}: {exc}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path}: {exc}")


def as_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_verdict(value: object) -> str:
    text = str(value or "").upper().strip()
    if text in VERDICT_ICON:
        return text
    return "WARN"


def normalize_severity(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in SEVERITY_ORDER:
        return text
    return "info"


def reviewer_name(reviewer: dict) -> str:
    name = reviewer.get("reviewer") or reviewer.get("perspective")
    return str(name or "unknown")


def perspective_name(reviewer: dict) -> str:
    perspective = reviewer.get("perspective")
    return str(perspective or "unknown")


def findings_for(reviewer: dict) -> list[dict]:
    findings = reviewer.get("findings")
    if isinstance(findings, list):
        return [finding for finding in findings if isinstance(finding, dict)]
    return []


def format_runtime(runtime_seconds: object) -> str:
    seconds = as_int(runtime_seconds)
    if seconds is None or seconds < 0:
        return "n/a"
    minutes, remainder = divmod(seconds, 60)
    if minutes > 0:
        return f"{minutes}m {remainder}s"
    return f"{seconds}s"


def format_confidence(confidence: object) -> str:
    if confidence is None:
        return "n/a"
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return "n/a"
    if value < 0 or value > 1:
        return "n/a"
    return f"{value:.2f}"


def summarize_reviewers(reviewers: list[dict]) -> str:
    total = len(reviewers)
    if total == 0:
        return "No reviewer verdicts available."

    groups: dict[str, list[str]] = {
        "PASS": [],
        "WARN": [],
        "FAIL": [],
        "SKIP": [],
    }
    for reviewer in reviewers:
        groups[normalize_verdict(reviewer.get("verdict"))].append(reviewer_name(reviewer))

    parts = [f"{len(groups['PASS'])}/{total} reviewers passed"]
    if groups["FAIL"]:
        parts.append(f"{len(groups['FAIL'])} failed ({', '.join(groups['FAIL'])})")
    if groups["WARN"]:
        parts.append(f"{len(groups['WARN'])} warned ({', '.join(groups['WARN'])})")
    if groups["SKIP"]:
        parts.append(f"{len(groups['SKIP'])} skipped ({', '.join(groups['SKIP'])})")
    return ". ".join(parts) + "."


def finding_location(finding: dict) -> str:
    path = str(finding.get("file") or "").strip()
    line = as_int(finding.get("line"))
    if path and line is not None and line > 0:
        return f"{path}:{line}"
    if path:
        return path
    return "location n/a"


def truncate(text: object, *, max_len: int) -> str:
    raw = str(text or "").strip()
    if len(raw) <= max_len:
        return raw
    return raw[: max_len - 1].rstrip() + "…"


def top_findings(reviewer: dict, *, max_findings: int) -> list[dict]:
    findings = findings_for(reviewer)
    return sorted(
        findings,
        key=lambda finding: (
            SEVERITY_ORDER.get(normalize_severity(finding.get("severity")), 99),
            str(finding.get("title") or ""),
            finding_location(finding),
        ),
    )[:max_findings]


def count_findings(reviewers: list[dict]) -> dict[str, int]:
    totals = {"critical": 0, "major": 0, "minor": 0, "info": 0}
    for reviewer in reviewers:
        stats = reviewer.get("stats")
        if isinstance(stats, dict):
            used_stats = False
            for severity in totals:
                value = as_int(stats.get(severity))
                if value is not None:
                    totals[severity] += max(0, value)
                    used_stats = True
            if used_stats:
                continue
        for finding in findings_for(reviewer):
            totals[normalize_severity(finding.get("severity"))] += 1
    return totals


def detect_skip_banner(reviewers: list[dict]) -> str:
    for reviewer in reviewers:
        if normalize_verdict(reviewer.get("verdict")) != "SKIP":
            continue
        findings = findings_for(reviewer)
        category = str(findings[0].get("category") or "").strip().lower() if findings else ""
        title = str(findings[0].get("title") or "").strip().upper() if findings else ""
        summary = str(reviewer.get("summary") or "").lower()

        if category == "api_error":
            if re.search(r"(CREDITS_DEPLETED|QUOTA_EXCEEDED)", title):
                return (
                    "> **⛔ API credits depleted for one or more reviewers.** "
                    "Some reviews were skipped because the API provider has no remaining credits."
                )
            if "KEY_INVALID" in title:
                return (
                    "> **🔑 API key error for one or more reviewers.** "
                    "Some reviews were skipped due to authentication failures."
                )
            return "> **⚠️ API error for one or more reviewers.** Some reviews were skipped due to API errors."

        if category == "timeout" or "timeout" in summary:
            return (
                "> **⏱️ One or more reviewers timed out.** "
                "Some reviews were skipped because they exceeded the configured runtime limit."
            )
    return ""


def scope_summary() -> str:
    changed_files = as_int(os.environ.get("PR_CHANGED_FILES"))
    additions = as_int(os.environ.get("PR_ADDITIONS"))
    deletions = as_int(os.environ.get("PR_DELETIONS"))
    if changed_files is None or additions is None or deletions is None:
        return "unknown scope (missing PR diff metadata)"
    return f"{changed_files} files changed, +{additions} / -{deletions} lines"


def run_link() -> tuple[str, str]:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    if not repo or not run_id:
        return ("n/a", "")
    return (f"#{run_id}", f"{server}/{repo}/actions/runs/{run_id}")


def short_sha() -> str:
    head_sha = str(os.environ.get("GH_HEAD_SHA") or "").strip()
    if not head_sha:
        return "<head-sha>"
    return head_sha[:12]


def footer_line() -> str:
    version = str(os.environ.get("CERBERUS_VERSION") or "dev").strip() or "dev"
    override_policy = str(os.environ.get("GH_OVERRIDE_POLICY") or "pr_author").strip() or "pr_author"
    fail_on_verdict = str(os.environ.get("FAIL_ON_VERDICT") or "true").strip() or "true"
    run_label, run_url = run_link()
    if run_url:
        run_fragment = f"[{run_label}]({run_url})"
    else:
        run_fragment = run_label
    return (
        f"*Cerberus Council ({version}) | Run {run_fragment} | "
        f"Override policy `{override_policy}` | Fail on verdict `{fail_on_verdict}` | "
        f"Override command: `/council override sha={short_sha()}` (reason required)*"
    )


def format_reviewer_block(reviewer: dict, *, max_findings: int) -> list[str]:
    verdict = normalize_verdict(reviewer.get("verdict"))
    icon = VERDICT_ICON[verdict]
    name = reviewer_name(reviewer)
    perspective = perspective_name(reviewer)
    runtime = format_runtime(reviewer.get("runtime_seconds"))
    confidence = format_confidence(reviewer.get("confidence"))
    findings = findings_for(reviewer)
    summary = truncate(reviewer.get("summary"), max_len=2000) or "No summary provided."

    lines = [
        "<details>",
        (
            f"<summary>{icon} <strong>{name}</strong> ({perspective}) | "
            f"{verdict} | confidence {confidence} | runtime {runtime} | findings {len(findings)}</summary>"
        ),
        "",
        f"- Verdict: `{verdict}`",
        f"- Confidence: `{confidence}`",
        f"- Runtime: `{runtime}`",
        f"- Summary: {summary}",
        "",
    ]

    if findings:
        lines.append("**Key findings**")
        for finding in top_findings(reviewer, max_findings=max_findings):
            severity = normalize_severity(finding.get("severity"))
            title = truncate(finding.get("title"), max_len=200) or "Untitled finding"
            category = truncate(finding.get("category"), max_len=80) or "uncategorized"
            location = finding_location(finding)
            description = truncate(finding.get("description"), max_len=1000)
            suggestion = truncate(finding.get("suggestion"), max_len=1000)
            lines.append(
                f"- `{severity}` **{title}** (`{category}`) at `{location}`"
            )
            if description:
                lines.append(f"  - {description}")
            if suggestion:
                lines.append(f"  - Suggestion: {suggestion}")
        hidden = len(findings) - max_findings
        if hidden > 0:
            lines.append(f"- Additional findings not shown: {hidden}")
    else:
        lines.append("_No findings reported._")

    raw_review = reviewer.get("raw_review")
    if raw_review and isinstance(raw_review, str) and raw_review.strip():
        lines.extend([
            "",
            "<details>",
            "<summary>Full review output (click to expand)</summary>",
            "",
            raw_review.strip(),
            "",
            "</details>",
        ])

    lines.extend(["", "</details>"])
    return lines


def _build_comment(
    *,
    marker: str,
    icon: str,
    verdict: str,
    summary_line: str,
    skip_banner: str,
    finding_totals: dict[str, int],
    reviewer_total: int,
    reviewer_pass: int,
    reviewer_warn: int,
    reviewer_fail: int,
    reviewer_skip: int,
    override: dict | None,
    reviewers: list[dict],
    max_findings: int,
    size_note: str = "",
) -> str:
    lines = [
        marker,
        f"## {icon} Council Verdict: {verdict}",
        "",
        f"**Summary:** {summary_line}",
    ]
    if skip_banner:
        lines.extend(["", skip_banner])

    lines.extend(
        [
            "",
            f"**Review Scope:** {scope_summary()}",
            (
                "**Reviewer Breakdown:** "
                f"{reviewer_total} total | {reviewer_pass} pass | {reviewer_warn} warn | "
                f"{reviewer_fail} fail | {reviewer_skip} skip"
            ),
            (
                "**Findings:** "
                f"{finding_totals['critical']} critical | {finding_totals['major']} major | "
                f"{finding_totals['minor']} minor | {finding_totals['info']} info"
            ),
        ]
    )

    if isinstance(override, dict) and override.get("used"):
        actor = str(override.get("actor") or "unknown")
        sha = str(override.get("sha") or "unknown")
        reason = truncate(override.get("reason"), max_len=120) or "n/a"
        lines.append(f"**Override:** active by `{actor}` on `{sha}`. Reason: {reason}")

    if size_note:
        lines.extend(["", size_note])

    lines.extend(["", "### Reviewer Details"])
    for reviewer in reviewers:
        lines.extend([""] + format_reviewer_block(reviewer, max_findings=max_findings))

    lines.extend(["", "---", footer_line(), ""])
    return "\n".join(lines)


def render_comment(council: dict, *, max_findings: int, marker: str) -> str:
    reviewers = council.get("reviewers")
    if not isinstance(reviewers, list):
        reviewers = []
    reviewers = [reviewer for reviewer in reviewers if isinstance(reviewer, dict)]
    reviewers = sorted(
        reviewers,
        key=lambda reviewer: (
            VERDICT_ORDER.get(normalize_verdict(reviewer.get("verdict")), 99),
            reviewer_name(reviewer),
        ),
    )

    verdict = normalize_verdict(council.get("verdict"))
    icon = VERDICT_ICON[verdict]
    summary_line = summarize_reviewers(reviewers)
    skip_banner = detect_skip_banner(reviewers)
    finding_totals = count_findings(reviewers)
    stats = council.get("stats")
    if not isinstance(stats, dict):
        stats = {}
    reviewer_total = as_int(stats.get("total"))
    reviewer_pass = as_int(stats.get("pass"))
    reviewer_warn = as_int(stats.get("warn"))
    reviewer_fail = as_int(stats.get("fail"))
    reviewer_skip = as_int(stats.get("skip"))
    if None in {reviewer_total, reviewer_pass, reviewer_warn, reviewer_fail, reviewer_skip}:
        reviewer_total = len(reviewers)
        reviewer_pass = len([r for r in reviewers if normalize_verdict(r.get("verdict")) == "PASS"])
        reviewer_warn = len([r for r in reviewers if normalize_verdict(r.get("verdict")) == "WARN"])
        reviewer_fail = len([r for r in reviewers if normalize_verdict(r.get("verdict")) == "FAIL"])
        reviewer_skip = len([r for r in reviewers if normalize_verdict(r.get("verdict")) == "SKIP"])

    common = dict(
        marker=marker,
        icon=icon,
        verdict=verdict,
        summary_line=summary_line,
        skip_banner=skip_banner,
        finding_totals=finding_totals,
        reviewer_total=reviewer_total,
        reviewer_pass=reviewer_pass,
        reviewer_warn=reviewer_warn,
        reviewer_fail=reviewer_fail,
        reviewer_skip=reviewer_skip,
        override=council.get("override"),
        reviewers=reviewers,
        max_findings=max_findings,
    )

    result = _build_comment(**common)

    # Guard against GitHub's 65,536-byte comment limit.
    # Strip raw_review blocks first (largest variable-size content).
    if len(result) > MAX_COMMENT_SIZE:
        for reviewer in reviewers:
            reviewer.pop("raw_review", None)
        result = _build_comment(
            **common,
            size_note=(
                "> **Note:** Raw review output was omitted to stay within GitHub's comment size limit. "
                "See the workflow run artifacts for full output."
            ),
        )

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Cerberus council comment markdown.")
    parser.add_argument(
        "--council-json",
        default="/tmp/council-verdict.json",
        help="Path to council verdict JSON.",
    )
    parser.add_argument(
        "--output",
        default="/tmp/council-comment.md",
        help="Output markdown file path.",
    )
    parser.add_argument(
        "--marker",
        default="<!-- cerberus:council -->",
        help="HTML marker for idempotent comment upsert.",
    )
    parser.add_argument(
        "--max-findings",
        type=int,
        default=10,
        help="Maximum findings to show per reviewer section.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.max_findings < 1:
        fail("--max-findings must be >= 1")

    council_path = Path(args.council_json)
    output_path = Path(args.output)

    council = read_json(council_path)
    markdown = render_comment(council, max_findings=args.max_findings, marker=args.marker)

    try:
        output_path.write_text(markdown, encoding="utf-8")
    except OSError as exc:
        fail(f"unable to write {output_path}: {exc}")


if __name__ == "__main__":
    main()
