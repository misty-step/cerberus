#!/usr/bin/env python3
"""Parse defaults/config.yml and output the reviewer matrix.

Usage:
    python3 generate-matrix.py <config-path>

Outputs three files:
    /tmp/matrix-output.json  — {"include": [{"reviewer": ..., "perspective": ...}, ...]}
    /tmp/matrix-count.txt    — number of reviewers
    /tmp/matrix-names.txt    — comma-separated reviewer names

Also prints to stdout for test consumption:
    Line 1: JSON matrix
    Line 2: count
    Line 3: comma-separated names
"""
import json
import sys

import yaml


def generate_matrix(config_path):
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    reviewers = config.get("reviewers", [])
    if not reviewers:
        print("No reviewers found in config", file=sys.stderr)
        sys.exit(1)

    matrix = []
    names = []
    for r in reviewers:
        name = r.get("name")
        perspective = r.get("perspective")
        if name and perspective:
            matrix.append({"reviewer": name, "perspective": perspective})
            names.append(name)

    matrix_json = json.dumps({"include": matrix})
    count = str(len(matrix))
    names_csv = ",".join(names)

    # Write output files (used by the GitHub Action)
    with open("/tmp/matrix-output.json", "w") as f:
        f.write(matrix_json)
    with open("/tmp/matrix-count.txt", "w") as f:
        f.write(count)
    with open("/tmp/matrix-names.txt", "w") as f:
        f.write(names_csv)

    # Print for stdout consumption (tests)
    print(matrix_json)
    print(count)
    print(names_csv)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <config-path>", file=sys.stderr)
        sys.exit(1)
    generate_matrix(sys.argv[1])
