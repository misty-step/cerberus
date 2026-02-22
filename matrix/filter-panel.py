#!/usr/bin/env python3
"""Filter the reviewer matrix to only include perspectives in the router panel.

Usage:
    python3 filter-panel.py <panel-json>

Reads /tmp/matrix-output.json, filters to matching perspectives,
and writes updated /tmp/matrix-output.json, /tmp/matrix-count.txt,
/tmp/matrix-names.txt.

If no reviewers match the panel, falls back to the full matrix with a warning.
"""
import json
import sys


def main():
    panel = json.loads(sys.argv[1])
    panel_set = set(panel)

    matrix = json.load(open("/tmp/matrix-output.json"))
    filtered = [r for r in matrix["include"] if r["perspective"] in panel_set]

    if not filtered:
        filtered = matrix["include"]
        print(
            "::warning::Panel filter matched no reviewers; using full matrix",
            file=sys.stderr,
        )

    json.dump({"include": filtered}, open("/tmp/matrix-output.json", "w"))
    open("/tmp/matrix-count.txt", "w").write(str(len(filtered)))
    open("/tmp/matrix-names.txt", "w").write(
        ",".join(r["reviewer"] for r in filtered)
    )


if __name__ == "__main__":
    main()
