"""Unified diff helpers for GitHub PR review comments.

GitHub's PR review APIs accept `position`, which is a 1-indexed line offset
within a file's diff patch (the `patch` field from `pulls/{pr}/files`).

This module maps new-file absolute line numbers to diff positions.
"""

from __future__ import annotations

import re

_HUNK_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)


def build_newline_to_position(patch: str) -> dict[int, int]:
    """Return map: new-file line number -> patch position (1-indexed).

    Only lines present in the patch (context or additions) are mapped.
    Deletions don't advance the new-file line counter.
    """
    mapping: dict[int, int] = {}
    new_line: int | None = None

    for position, raw in enumerate((patch or "").splitlines(), start=1):
        m = _HUNK_RE.match(raw)
        if m:
            new_line = int(m.group("new_start"))
            continue

        if new_line is None:
            continue

        if not raw:
            continue

        prefix = raw[0]
        if prefix == "\\":
            # "\ No newline at end of file" marker line.
            continue

        if prefix in {" ", "+"}:
            mapping[new_line] = position
            new_line += 1
            continue

        if prefix == "-":
            continue

    return mapping
