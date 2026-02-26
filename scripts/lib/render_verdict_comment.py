#!/usr/bin/env python3
"""Render a scannable Cerberus verdict PR comment from verdict JSON."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from lib.findings import (
    SEVERITY_ORDER,
    as_int,
    format_reviewer_list,
    group_findings,
    normalize_severity,
    reviewer_label,
    split_reviewer_description,
)
from lib.markdown import details_block, location_link, repo_context, severity_icon

# GitHub PR comments are silently rejected above 65,536 bytes.
# Budget headroom so the structural markdown always fits.
MAX_COMMENT_SIZE = 60000

VERDICT_ICON = {
    "PASS": "✅",
    "WARN": "⚠️",
    "FAIL": "❌",
    "SKIP": "⏭️",
}

VERDICT_ORDER = {
    "FAIL": 0,
    "WARN": 1,
    "SKIP": 2,
    "PASS": 3,
}

CERBERUS_TMP = Path(os.environ.get("CERBERUS_TMP", tempfile.gettempdir()))


def fail(message: str, code: int = 2) -> int:
    """Fail."""
    print(f"render-verdict-comment: {message}", file=sys.stderr)
    return code


def read_json(path: Path) -> dict:
    """Read json."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise IOError(f"unable to read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"invalid JSON in {path}: expected object")
    return data


def normalize_verdict(value: object) -> str:
    """Normalize verdict."""
    text = str(value or "").upper().strip()
    if text in VERDICT_ICON:
        return text
    return "WARN"


def reviewer_name(reviewer: dict) -> str:
    """Reviewer name."""
    name = reviewer.get("reviewer") or reviewer.get("perspective")
    return str(name or "unknown")


def normalize_wave(value: object) -> str:
    """Normalize wave identifiers for display and grouping."""
    text = str(value or "").strip().lower()
    if not text:
        return "unscoped"
    normalized = text.replace("_", "").replace("-", "")
    if normalized.startswith("wave") and normalized[4:].isdigit():
        return f"wave{int(normalized[4:])}"
    return text


def wave_label(value: object) -> str:
    """Human-friendly wave label."""
    wave = normalize_wave(value)
    if wave.startswith("wave") and wave[4:].isdigit():
        return f"Wave {int(wave[4:])}"
    if wave == "unscoped":
        return "Unscoped"
    return wave


def reviewer_wave(reviewer: dict) -> str:
    """Resolve reviewer wave from verdict metadata."""
    return normalize_wave(reviewer.get("model_wave") or reviewer.get("wave"))


def wave_sort_key(wave: str) -> tuple[int, int | str]:
    """Stable display order for wave summaries."""
    if wave.startswith("wave") and wave[4:].isdigit():
        return (0, int(wave[4:]))
    if wave == "unscoped":
        return (2, 0)
    return (1, wave)


def perspective_name(reviewer: dict) -> str:
    """Perspective name."""
    perspective = reviewer.get("perspective")
    return str(perspective or "unknown")


_CODENAME_RE = re.compile(r"^[A-Z0-9_]+$")


def friendly_codename(value: object) -> str:
    """Friendly codename."""
    raw = str(value or "").strip() or "unknown"
    # Legacy ALLCAPS codenames (APOLLO, etc.) → Title Case for readability.
    # New lowercase codenames (trace, atlas, etc.) → pass through as-is.
    if raw.isupper() and _CODENAME_RE.match(raw):
        return raw.title()
    return raw


def reviewer_overview_title(reviewer: dict) -> str:
    """Reviewer overview title."""
    label = reviewer_label(reviewer)
    code = friendly_codename(reviewer_name(reviewer))
    if not code or code == "unknown":
        return f"**{label}**"
    if label == code:
        return f"**{label}**"
    return f"**{label}** ({code})"


def findings_for(reviewer: dict) -> list[dict]:
    """Findings for."""
    findings = reviewer.get("findings")
    if isinstance(findings, list):
        return [finding for finding in findings if isinstance(finding, dict)]
    return []


def format_runtime(runtime_seconds: object) -> str:
    """Format runtime."""
    seconds = as_int(runtime_seconds)
    if seconds is None or seconds < 0:
        return "n/a"
    minutes, remainder = divmod(seconds, 60)
    if minutes > 0:
        return f"{minutes}m {remainder}s"
    return f"{seconds}s"


def short_model_name(model: str) -> str:
    """Strip provider prefixes for brevity: openrouter/moonshotai/kimi-k2.5 → kimi-k2.5"""
    if model.startswith("openrouter/"):
        model = model[len("openrouter/"):]
    return model.rsplit("/", 1)[-1] if "/" in model else model


def format_model(reviewer: dict) -> str | None:
    """Format model."""
    model_used = reviewer.get("model_used")
    if not model_used or not isinstance(model_used, str):
        return None
    short = short_model_name(model_used)
    if reviewer.get("fallback_used"):
        primary = reviewer.get("primary_model")
        if primary and isinstance(primary, str):
            primary_short = short_model_name(primary)
            return f"`{short}` ↩️ (fallback from `{primary_short}`)"
    return f"`{short}`"


def format_confidence(confidence: object) -> str:
    """Format confidence."""
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
    """Summarize reviewers."""
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
        groups[normalize_verdict(reviewer.get("verdict"))].append(reviewer_label(reviewer))

    parts = [f"{len(groups['PASS'])}/{total} reviewers passed"]
    if groups["FAIL"]:
        parts.append(f"{len(groups['FAIL'])} failed ({', '.join(groups['FAIL'])})")
    if groups["WARN"]:
        parts.append(f"{len(groups['WARN'])} warned ({', '.join(groups['WARN'])})")
    if groups["SKIP"]:
        parts.append(f"{len(groups['SKIP'])} skipped ({', '.join(groups['SKIP'])})")
    return ". ".join(parts) + "."


def finding_location(finding: dict) -> str:
    """Finding location."""
    path = str(finding.get("file") or "").strip()
    line = as_int(finding.get("line"))
    if path and line is not None and line > 0:
        return f"{path}:{line}"
    if path:
        return path
    return "location n/a"


def finding_location_link(finding: dict) -> str:
    """Finding location link."""
    path = str(finding.get("file") or "").strip()
    line = as_int(finding.get("line"))
    if line is not None and line <= 0:
        line = None
    server, repo, sha = repo_context()
    return location_link(
        path,
        line,
        server=server,
        repo=repo,
        sha=sha,
        missing_label="location n/a",
    )


def truncate(text: object, *, max_len: int) -> str:
    """Truncate."""
    raw = str(text or "").strip()
    if len(raw) <= max_len:
        return raw
    return raw[: max_len - 1].rstrip() + "…"


def top_findings(reviewer: dict, *, max_findings: int) -> list[dict]:
    """Top findings."""
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
    """Count findings."""
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
    """Detect skip banner."""
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
            if re.search(r"\bRATE_LIMIT\b", title):
                return (
                    "> **⏩ Rate limit exceeded for one or more reviewers.** "
                    "Some reviews were skipped due to provider rate limiting."
                )
            if re.search(r"SERVICE_UNAVAILABLE|503", title):
                return (
                    "> **🔌 Provider unavailable for one or more reviewers.** "
                    "Some reviews were skipped because the API provider returned a service error."
                )
            return "> **⚠️ API error for one or more reviewers.** Some reviews were skipped due to API errors."

        if category == "timeout" or "timeout" in summary:
            return (
                "> **⏱️ One or more reviewers timed out.** "
                "Some reviews were skipped because they exceeded the configured runtime limit."
            )

        if category == "parse-failure":
            return (
                "> **📝 One or more reviewers could not be parsed.** "
                "Some reviews were skipped because the model output lacked a structured JSON block."
            )

    return ""


def classify_skip_reviewer(reviewer: dict) -> dict:
    """Classify skip reason for a single reviewer.

    Returns dict with ``reason`` (human-readable) and ``recovery`` (actionable step).
    """
    findings = findings_for(reviewer)
    category = str(findings[0].get("category") or "").strip().lower() if findings else ""
    title = str(findings[0].get("title") or "").strip().upper() if findings else ""
    summary = str(reviewer.get("summary") or "").lower()

    # Timeout — aligned with detect_skip_banner (checks "timeout" in summary broadly)
    if category == "timeout" or "timeout" in summary:
        m = re.search(r"timeout after (\d+)s", summary)
        duration = f" ({m.group(1)}s)" if m else ""
        return {
            "reason": f"Timeout{duration}",
            "recovery": "Increase `timeout` input or break PR into smaller changes.",
        }

    # API errors — sub-classified by finding title
    if category == "api_error":
        if re.search(r"CREDITS_DEPLETED|QUOTA_EXCEEDED", title):
            return {
                "reason": "API credits exhausted",
                "recovery": "Add credits at your API provider or configure a fallback model.",
            }
        if "KEY_INVALID" in title:
            return {
                "reason": "Auth error (invalid key)",
                "recovery": "Check that the API key secret is set and valid.",
            }
        if re.search(r"\bRATE_LIMIT\b", title):
            return {
                "reason": "Rate limit exceeded",
                "recovery": "Wait and retry, or reduce reviewer concurrency.",
            }
        if re.search(r"SERVICE_UNAVAILABLE|503", title):
            return {
                "reason": "Service unavailable",
                "recovery": "Check provider status and retry later.",
            }
        return {
            "reason": "API error",
            "recovery": "Check API key and quota settings.",
        }

    # Parse failure — detected by finding category or summary prefix
    if category == "parse-failure" or summary.startswith("review output could not be parsed"):
        return {
            "reason": "Parse failure",
            "recovery": "Check workflow logs/artifacts; consider a more capable model.",
        }

    # Network / infrastructure errors detected in summary
    if re.search(r"service.unavailable|503|network|connection", summary):
        return {
            "reason": "Network error",
            "recovery": "Check provider status at your API provider and retry.",
        }

    return {
        "reason": "Unknown",
        "recovery": "Check workflow logs and artifacts for details.",
    }


def format_skip_diagnostics_table(skip_reviewers: list[dict]) -> list[str]:
    """Render a '### Skipped Reviews' diagnostics table for the verdict comment."""
    if not skip_reviewers:
        return []

    lines = [
        "### Skipped Reviews",
        "",
        "| Reviewer | Reason | Recovery |",
        "|----------|--------|----------|",
    ]
    for reviewer in skip_reviewers:
        label = reviewer_label(reviewer).replace("|", "&#124;")
        diag = classify_skip_reviewer(reviewer)
        reason = diag["reason"].replace("|", "&#124;")
        recovery = diag["recovery"].replace("|", "&#124;")
        lines.append(f"| {label} | {reason} | {recovery} |")
    return lines


def scope_summary() -> str:
    """Scope summary."""
    changed_files = as_int(os.environ.get("PR_CHANGED_FILES"))
    additions = as_int(os.environ.get("PR_ADDITIONS"))
    deletions = as_int(os.environ.get("PR_DELETIONS"))
    if changed_files is None or additions is None or deletions is None:
        return "unknown scope (missing PR diff metadata)"
    return f"{changed_files} files changed, +{additions} / -{deletions} lines"


def run_link() -> tuple[str, str]:
    """Run link."""
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    if not repo or not run_id:
        return ("n/a", "")
    return (f"#{run_id}", f"{server}/{repo}/actions/runs/{run_id}")


def short_sha() -> str:
    """Short sha."""
    head_sha = str(os.environ.get("GH_HEAD_SHA") or "").strip()
    if not head_sha:
        return "<head-sha>"
    return head_sha[:12]


def footer_line() -> str:
    """Footer line."""
    version = str(os.environ.get("CERBERUS_VERSION") or "dev").strip() or "dev"
    override_policy = str(os.environ.get("GH_OVERRIDE_POLICY") or "pr_author").strip() or "pr_author"
    fail_on_verdict = str(os.environ.get("FAIL_ON_VERDICT") or "true").strip() or "true"
    run_label, run_url = run_link()
    if run_url:
        run_fragment = f"[{run_label}]({run_url})"
    else:
        run_fragment = run_label
    return (
        f"*Cerberus ({version}) | Run {run_fragment} | "
        f"Override policy `{override_policy}` | Fail on verdict `{fail_on_verdict}` | "
        f"Override command: `/cerberus override sha={short_sha()}` (reason required)*"
    )


def format_reviewer_overview_lines(reviewers: list[dict]) -> list[str]:
    """Format reviewer overview lines."""
    if not reviewers:
        return ["- No reviewer verdicts available."]

    lines: list[str] = []
    for reviewer in reviewers:
        verdict = normalize_verdict(reviewer.get("verdict"))
        icon = VERDICT_ICON[verdict]
        title = reviewer_overview_title(reviewer)
        runtime = format_runtime(reviewer.get("runtime_seconds"))
        confidence = format_confidence(reviewer.get("confidence"))
        model_label = format_model(reviewer)
        finding_count = len(findings_for(reviewer))
        wave = wave_label(reviewer_wave(reviewer))

        parts = [
            f"{icon} {title}",
            f"`{verdict}`",
            f"{finding_count} findings",
            f"wave `{wave}`",
            f"conf `{confidence}`",
            f"runtime `{runtime}`",
        ]
        if model_label:
            parts.append(f"model {model_label}")
        lines.append("- " + " | ".join(parts))

    return lines


def format_wave_summary_lines(reviewers: list[dict]) -> list[str]:
    """Format wave-level verdict summary lines."""
    if not reviewers:
        return []

    by_wave: dict[str, dict[str, int]] = {}
    for reviewer in reviewers:
        wave = reviewer_wave(reviewer)
        verdict = normalize_verdict(reviewer.get("verdict"))
        entry = by_wave.setdefault(
            wave,
            {"total": 0, "pass": 0, "warn": 0, "fail": 0, "skip": 0, "findings": 0},
        )
        entry["total"] += 1
        entry[verdict.lower()] = entry.get(verdict.lower(), 0) + 1
        entry["findings"] += len(findings_for(reviewer))

    lines: list[str] = []
    for wave in sorted(by_wave.keys(), key=wave_sort_key):
        stats = by_wave[wave]
        lines.append(
            "- "
            f"**{wave_label(wave)}**: {stats['total']} reviewers | "
            f"{stats['pass']} pass | {stats['warn']} warn | {stats['fail']} fail | "
            f"{stats['skip']} skip | {stats['findings']} findings"
        )
    return lines


def has_raw_output(reviewers: list[dict]) -> bool:
    """Has raw output."""
    for reviewer in reviewers:
        raw_review = reviewer.get("raw_review")
        if isinstance(raw_review, str) and raw_review.strip():
            return True
    return False


def collect_key_findings(reviewers: list[dict], *, max_total: int) -> list[tuple[str, dict]]:
    """Collect key findings."""
    items: list[tuple[str, dict]] = []
    for reviewer in reviewers:
        rname = reviewer_label(reviewer)
        for finding in findings_for(reviewer):
            items.append((rname, finding))

    def _sort_key(item: tuple[str, dict]) -> tuple[int, str, str, str]:
        rname, finding = item
        return (
            SEVERITY_ORDER.get(normalize_severity(finding.get("severity")), 99),
            str(finding.get("title") or ""),
            finding_location(finding),
            rname,
        )

    return sorted(items, key=_sort_key)[:max_total]


def collect_issue_groups(reviewers: list[dict]) -> list[dict]:
    """Aggregate duplicate findings across reviewers into 'issues' keyed by (file,line,category,title)."""
    def _predicate(finding: dict, _rname: str) -> bool:
        file = str(finding.get("file") or "").strip()
        return bool(file) and file.upper() != "N/A"

    out = group_findings(
        ((reviewer_label(rv), findings_for(rv)) for rv in reviewers),
        text_fields=("suggestion",),
        predicate=_predicate,
        severity_order=SEVERITY_ORDER,
    )

    def _sort_key(item: dict) -> tuple[int, int, str, int, str]:
        return (
            SEVERITY_ORDER.get(normalize_severity(item.get("severity")), 99),
            -len(item.get("reviewers") or []),
            str(item.get("file") or ""),
            int(item.get("line") or 0),
            str(item.get("title") or ""),
        )

    out.sort(key=_sort_key)
    return out


def format_fix_order_lines(reviewers: list[dict], *, max_items: int) -> list[str]:
    """Format fix order lines."""
    items = collect_issue_groups(reviewers)
    if not items:
        return ["_No findings reported._"]

    server, repo, sha = repo_context()
    lines: list[str] = []
    for i, item in enumerate(items[:max_items], start=1):
        severity = normalize_severity(item.get("severity"))
        sev_icon = severity_icon(severity)
        title = truncate(item.get("title"), max_len=200) or "Untitled finding"
        category = truncate(item.get("category"), max_len=80) or "uncategorized"
        file = str(item.get("file") or "").strip()
        line = as_int(item.get("line"))
        if line is not None and line <= 0:
            line = None
        location = location_link(file, line, server=server, repo=repo, sha=sha, missing_label="location n/a")
        who = format_reviewer_list(item.get("reviewers") or [])
        fix = truncate(item.get("suggestion"), max_len=240)

        lines.append(f"{i}. {sev_icon} **{title}** (`{category}`) at {location} ({who})")
        if fix:
            lines.append(f"   Fix: {fix}")

    return lines


def collect_hotspots(reviewers: list[dict]) -> list[dict]:
    """Collect hotspots."""
    by_file: dict[str, dict] = {}
    for reviewer in reviewers:
        rname = reviewer_label(reviewer)
        for finding in findings_for(reviewer):
            file = str(finding.get("file") or "").strip()
            if not file or file.upper() == "N/A":
                continue
            severity = normalize_severity(finding.get("severity"))
            entry = by_file.get(file)
            if entry is None:
                entry = {
                    "file": file,
                    "reviewers": set(),
                    "counts": {"critical": 0, "major": 0, "minor": 0, "info": 0},
                    "worst": 99,
                    "total": 0,
                }
                by_file[file] = entry
            entry["reviewers"].add(rname)
            entry["counts"][severity] = entry["counts"].get(severity, 0) + 1
            entry["total"] += 1
            entry["worst"] = min(entry["worst"], SEVERITY_ORDER.get(severity, 99))

    out: list[dict] = []
    for entry in by_file.values():
        entry["reviewers"] = sorted(str(r or "").strip() for r in entry.get("reviewers", set()) if str(r or "").strip())
        out.append(entry)

    def _sort_key(item: dict) -> tuple[int, int, int, int, int, str]:
        counts = item.get("counts") or {}
        return (
            -len(item.get("reviewers") or []),
            int(item.get("worst") or 99),
            -int(counts.get("critical") or 0),
            -int(counts.get("major") or 0),
            -int(item.get("total") or 0),
            str(item.get("file") or ""),
        )

    out.sort(key=_sort_key)
    return out


def format_hotspots_lines(reviewers: list[dict], *, max_files: int) -> list[str]:
    """Format hotspots lines."""
    hotspots = collect_hotspots(reviewers)[:max_files]
    if not hotspots:
        return ["_No hotspots detected._"]

    server, repo, sha = repo_context()
    lines: list[str] = []
    for item in hotspots:
        file = str(item.get("file") or "").strip()
        counts = item.get("counts") or {}
        who = len(item.get("reviewers") or [])
        link = location_link(file, None, server=server, repo=repo, sha=sha, missing_label="location n/a")
        lines.append(
            f"- {link} — {who} reviewers | {counts.get('critical', 0)} critical | "
            f"{counts.get('major', 0)} major | {counts.get('minor', 0)} minor"
        )
    return lines


def format_key_findings_lines(reviewers: list[dict], *, max_total: int) -> list[str]:
    """Format key findings lines."""
    items = collect_key_findings(reviewers, max_total=max_total)
    if not items:
        return ["_No findings reported._"]

    lines: list[str] = []
    for rname, finding in items:
        severity = normalize_severity(finding.get("severity"))
        sev_icon = severity_icon(severity)
        title = truncate(finding.get("title"), max_len=200) or "Untitled finding"
        category = truncate(finding.get("category"), max_len=80) or "uncategorized"
        location = finding_location_link(finding)
        description = truncate(finding.get("description"), max_len=1000)
        suggestion = truncate(finding.get("suggestion"), max_len=1000)

        lines.append(f"- {sev_icon} **{title}** (`{category}`) at {location} ({rname})")

        detail_lines: list[str] = []
        if description:
            detail_lines.append(f"Description: {description}")
        if suggestion:
            detail_lines.append(f"Suggestion: {suggestion}")
        lines.extend(details_block(detail_lines, summary="Details", indent="  "))

    return lines


def format_reviewer_details_block(reviewers: list[dict], *, max_findings: int) -> list[str]:
    """Format reviewer details block."""
    lines = [
        "<details>",
        "<summary>Reviewer details (click to expand)</summary>",
        "",
    ]

    for reviewer in reviewers:
        verdict = normalize_verdict(reviewer.get("verdict"))
        icon = VERDICT_ICON[verdict]
        label = reviewer_label(reviewer)
        code = friendly_codename(reviewer_name(reviewer))
        _, tagline = split_reviewer_description(reviewer.get("reviewer_description"))
        runtime = format_runtime(reviewer.get("runtime_seconds"))
        confidence = format_confidence(reviewer.get("confidence"))
        model_label = format_model(reviewer)
        findings = findings_for(reviewer)
        summary = truncate(reviewer.get("summary"), max_len=2000) or "No summary provided."

        if code and code != "unknown" and code != label:
            header = f"{label} ({code})"
        else:
            header = label
        lines.append(f"#### {icon} {header} — {verdict}")
        lines.append("")
        lines.append(f"- Confidence: `{confidence}`")
        lines.append(f"- Wave: `{wave_label(reviewer_wave(reviewer))}`")
        if model_label:
            lines.append(f"- Model: {model_label}")
        lines.append(f"- Runtime: `{runtime}`")
        if tagline:
            lines.append(f"- Focus: {tagline}")
        lines.append(f"- Summary: {summary}")
        lines.append("")

        if findings:
            lines.append("**Findings**")
            for finding in top_findings(reviewer, max_findings=max_findings):
                severity = normalize_severity(finding.get("severity"))
                sev_icon = severity_icon(severity)
                title = truncate(finding.get("title"), max_len=200) or "Untitled finding"
                category = truncate(finding.get("category"), max_len=80) or "uncategorized"
                location = finding_location_link(finding)
                description = truncate(finding.get("description"), max_len=1000)
                suggestion = truncate(finding.get("suggestion"), max_len=1000)
                lines.append(f"- {sev_icon} **{title}** (`{category}`) at {location}")
                if description:
                    lines.append(f"  - {description}")
                if suggestion:
                    lines.append(f"  - Suggestion: {suggestion}")
            hidden = len(findings) - max_findings
            if hidden > 0:
                lines.append(f"- Additional findings not shown: {hidden}")
        else:
            lines.append("_No findings reported._")

        lines.append("")

    lines.append("</details>")
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
    detail_reviewers: list[dict],
    include_fix_order: bool,
    include_hotspots: bool,
    include_key_findings: bool,
    include_reviewer_details: bool,
    max_fix_items: int,
    max_hotspots: int,
    max_findings: int,
    max_key_findings: int,
    raw_output_note: str = "",
    size_note: str = "",
    advisory_banner: str = "",
    skip_diagnostics_table: list[str],
) -> str:
    verdict_label = f"{verdict} (advisory)" if advisory_banner else verdict
    lines = [
        marker,
        f"## {icon} Cerberus Verdict: {verdict_label}",
        "",
        f"**Summary:** {summary_line}",
    ]
    if advisory_banner:
        lines.extend(["", advisory_banner])
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

    if raw_output_note:
        lines.extend(["", raw_output_note])
    if size_note:
        lines.extend(["", size_note])

    if skip_diagnostics_table:
        lines.extend(["", *skip_diagnostics_table])

    wave_summary_lines = format_wave_summary_lines(reviewers)
    if wave_summary_lines:
        lines.extend(["", "### Wave Summary"])
        lines.extend(wave_summary_lines)

    # Progressive disclosure: collapse details on PASS, show key findings on WARN/FAIL
    is_fail_or_warn = verdict in ("FAIL", "WARN")

    if include_fix_order and is_fail_or_warn:
        lines.extend(["", "### Fix Order"])
        lines.extend(format_fix_order_lines(reviewers, max_items=max_fix_items))

    if include_hotspots and is_fail_or_warn:
        lines.extend(["", "### Hotspots"])
        lines.extend(format_hotspots_lines(reviewers, max_files=max_hotspots))

    if reviewers:
        # Always wrap in <details> for progressive disclosure
        lines.extend(["", "### Reviewer Overview"])
        lines.extend(["<details>", "<summary>(click to expand)</summary>", ""])
        lines.extend(format_reviewer_overview_lines(reviewers))
        lines.extend(["", "</details>"])

    if include_key_findings:
        lines.extend(["", "### Key Findings"])
        if is_fail_or_warn:
            # On WARN/FAIL: show key findings expanded by default
            lines.extend(["<details open>", "<summary>(show less)</summary>", ""])
            lines.extend(format_key_findings_lines(reviewers, max_total=max_key_findings))
            lines.extend(["", "</details>"])
        else:
            # PASS, SKIP, or other verdicts: collapse by default
            lines.extend(["<details>", "<summary>(click to expand)</summary>", ""])
            lines.extend(format_key_findings_lines(reviewers, max_total=max_key_findings))
            lines.extend(["", "</details>"])

    if include_reviewer_details and detail_reviewers:
        lines.extend(["", *format_reviewer_details_block(detail_reviewers, max_findings=max_findings)])

    lines.extend(["", "---", footer_line(), ""])
    return "\n".join(lines)


def render_comment(
    verdict_data: dict,
    *,
    max_findings: int,
    max_key_findings: int,
    marker: str,
) -> str:
    """Render comment."""
    reviewers = verdict_data.get("reviewers")
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

    verdict = normalize_verdict(verdict_data.get("verdict"))
    icon = VERDICT_ICON[verdict]
    summary_line = summarize_reviewers(reviewers)
    skip_banner = detect_skip_banner(reviewers)
    finding_totals = count_findings(reviewers)
    stats = verdict_data.get("stats")
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

    raw_note = ""
    if has_raw_output(reviewers):
        raw_note = (
            "> **Note:** One or more reviewers produced unstructured output. "
            "Raw output is preserved in workflow artifacts/logs, but omitted from PR comments."
        )

    skip_reviewers_list = [r for r in reviewers if normalize_verdict(r.get("verdict")) == "SKIP"]
    skip_diagnostics_table = format_skip_diagnostics_table(skip_reviewers_list)

    advisory_banner = ""
    if (
        os.environ.get("FAIL_ON_VERDICT", "true").strip().lower() == "false"
        and verdict == "FAIL"
    ):
        advisory_banner = (
            "> ⚠️ **Advisory mode:** `fail-on-verdict` is disabled — this is a FAIL verdict "
            "but the check run is green. Set `fail-on-verdict: \"true\"` in your workflow to gate merges on failures."
        )
    elif (
        os.environ.get("FAIL_ON_SKIP", "false").strip().lower() == "false"
        and verdict == "SKIP"
    ):
        advisory_banner = (
            "> ⚠️ **Advisory mode:** `fail-on-skip` is disabled — all reviewers were skipped "
            "but the check run is green. Set `fail-on-skip: \"true\"` in your workflow to gate merges on skipped reviews."
        )

    total_findings = sum(len(findings_for(r)) for r in reviewers)
    include_key_findings = total_findings > 0
    include_fix_order = verdict in ("FAIL", "WARN") and total_findings > 0
    include_hotspots = verdict in ("FAIL", "WARN") and total_findings > 0

    detail_reviewers = [
        r for r in reviewers
        if normalize_verdict(r.get("verdict")) != "PASS" or len(findings_for(r)) > 0
    ]

    include_reviewer_details = verdict != "PASS" or include_key_findings or bool(raw_note)

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
        override=verdict_data.get("override"),
        reviewers=reviewers,
        detail_reviewers=detail_reviewers,
        include_fix_order=include_fix_order,
        include_hotspots=include_hotspots,
        include_key_findings=include_key_findings,
        include_reviewer_details=include_reviewer_details,
        max_fix_items=3,
        max_hotspots=5,
        max_findings=max_findings,
        max_key_findings=max_key_findings,
        raw_output_note=raw_note,
        advisory_banner=advisory_banner,
        skip_diagnostics_table=skip_diagnostics_table,
    )

    result = _build_comment(**common)

    # Guard against GitHub's 65,536-byte comment limit.
    if len(result) > MAX_COMMENT_SIZE:
        truncated = dict(common)
        truncated["include_reviewer_details"] = False
        truncated["max_findings"] = min(max_findings, 3)
        truncated["max_key_findings"] = min(max_key_findings, 5)
        truncated["size_note"] = (
            "> **Note:** Comment was truncated to stay within GitHub's size limit. "
            "See the workflow run for full details."
        )
        result = _build_comment(**truncated)

    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse args."""
    parser = argparse.ArgumentParser(description="Render Cerberus verdict comment markdown.")
    parser.add_argument(
        "--verdict-json",
        default=str(CERBERUS_TMP / "verdict.json"),
        help="Path to verdict JSON.",
    )
    parser.add_argument(
        "--output",
        default=str(CERBERUS_TMP / "verdict-comment.md"),
        help="Output markdown file path.",
    )
    parser.add_argument(
        "--marker",
        default="<!-- cerberus:verdict -->",
        help="HTML marker for idempotent comment upsert.",
    )
    parser.add_argument(
        "--max-findings",
        type=int,
        default=10,
        help="Maximum findings to show per reviewer section.",
    )
    parser.add_argument(
        "--max-key-findings",
        type=int,
        default=10,
        help="Maximum findings to show in the Key Findings section.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Main."""
    args = parse_args(argv)
    if args.max_findings < 1:
        return fail("--max-findings must be >= 1")
    if args.max_key_findings < 1:
        return fail("--max-key-findings must be >= 1")

    verdict_path = Path(args.verdict_json)
    output_path = Path(args.output)

    try:
        verdict_data = read_json(verdict_path)
    except (OSError, ValueError) as exc:
        return fail(str(exc))
    markdown = render_comment(
        verdict_data,
        max_findings=args.max_findings,
        max_key_findings=args.max_key_findings,
        marker=args.marker,
    )

    try:
        output_path.write_text(markdown, encoding="utf-8")
    except OSError as exc:
        return fail(f"unable to write {output_path}: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
