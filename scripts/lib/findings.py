"""Finding aggregation and formatting helpers.

Intentionally tiny: normalization + merging + reviewer list formatting.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

_SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "info": 3}


def norm_key(value: object) -> str:
    """Normalize arbitrary input into a stable grouping key."""
    return " ".join(str(value or "").strip().lower().split())


def best_text(a: object, b: object) -> str:
    """Prefer the longer non-empty string (keeps more context without merging prose)."""
    a_text = str(a or "").strip()
    b_text = str(b or "").strip()
    if not a_text:
        return b_text
    if not b_text:
        return a_text
    return b_text if len(b_text) > len(a_text) else a_text


def format_reviewer_list(value: object) -> str:
    """Format reviewer names into a compact, readable list."""
    names: list[str] = []
    if value is None:
        names = []
    elif isinstance(value, str):
        names = [value]
    elif isinstance(value, Iterable):
        names = [str(v or "") for v in value]
    else:
        names = [str(value)]

    names = [n.strip() for n in names if str(n or "").strip()]
    if not names:
        return "unknown"
    if len(names) <= 3:
        return ", ".join(names)
    return f"{names[0]}, {names[1]}, +{len(names) - 2}"


def _as_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _normalize_sev(value: object, order: dict[str, int]) -> str:
    text = " ".join(str(value or "").strip().lower().split())
    return text if text in order else "info"


def group_findings(
    findings_by_reviewer: Iterable[tuple[str, Iterable[object]]],
    *,
    text_fields: tuple[str, ...] = ("suggestion",),
    predicate: Callable[[dict, str], bool] | None = None,
    severity_order: dict[str, int] | None = None,
) -> list[dict]:
    """Group and merge findings from multiple reviewers by (file, line, category, title).

    Deduplicates matching findings, takes the worst severity, and merges text
    fields with best_text. Returns a list of finding dicts with "reviewers" as
    a sorted list of names.

    Args:
        findings_by_reviewer: Iterable of (reviewer_name, findings) pairs.
        text_fields: Fields to merge using best_text. Defaults to ("suggestion",).
        predicate: Optional filter called on each raw finding before processing.
                   Signature: predicate(finding_dict, reviewer_name) -> bool.
        severity_order: Severity ranking dict (lower int = more severe).
                        Defaults to the standard critical/major/minor/info order.
    """
    order = severity_order if severity_order is not None else _SEVERITY_ORDER
    grouped: dict[tuple[str, int, str, str], dict] = {}

    for rname, findings in findings_by_reviewer:
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            if predicate is not None and not predicate(finding, rname):
                continue

            file = str(finding.get("file") or "").strip()
            line = _as_int(finding.get("line")) or 0
            if line < 0:
                line = 0

            severity = _normalize_sev(finding.get("severity"), order)
            category = str(finding.get("category") or "").strip() or "uncategorized"
            title = str(finding.get("title") or "").strip() or "Untitled finding"

            key = (file, line, norm_key(category), norm_key(title))
            existing = grouped.get(key)
            if existing is None:
                grouped[key] = {
                    "severity": severity,
                    "category": category,
                    "file": file,
                    "line": line,
                    "title": title,
                    "reviewers": {rname},
                    **{field: str(finding.get(field) or "").strip() for field in text_fields},
                }
                continue

            existing["reviewers"].add(rname)
            if order.get(severity, 99) < order.get(existing.get("severity"), 99):
                existing["severity"] = severity
            for field in text_fields:
                existing[field] = best_text(existing.get(field), finding.get(field))

    out: list[dict] = []
    for item in grouped.values():
        reviewers = sorted(
            str(r or "").strip() for r in item.get("reviewers", set()) if str(r or "").strip()
        )
        item["reviewers"] = reviewers
        out.append(item)
    return out
