"""Finding aggregation and formatting helpers.

Intentionally tiny: normalization + merging + reviewer list formatting.
"""

from __future__ import annotations

from collections.abc import Iterable


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

