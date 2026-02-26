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
import os
import sys

import yaml


def split_description(value: object) -> tuple[str, str]:
    """Split description."""
    text = str(value or "").strip()
    if not text:
        return ("", "")
    if "—" in text:
        left, right = text.split("—", 1)
        return (left.strip(), right.strip())
    if " - " in text:
        left, right = text.split(" - ", 1)
        return (left.strip(), right.strip())
    return (text, "")


def generate_matrix(config_path):
    """Generate matrix."""
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    reviewers = config.get("reviewers", [])
    if not reviewers:
        print("No reviewers found in config", file=sys.stderr)
        sys.exit(1)

    review_wave = os.getenv("REVIEW_WAVE", "").strip().lower()
    if review_wave:
        wave_reviewers = []
        waves = config.get("waves") if isinstance(config, dict) else {}
        if isinstance(waves, dict):
            definitions = waves.get("definitions")
            if isinstance(definitions, dict):
                wave_cfg = definitions.get(review_wave)
                if isinstance(wave_cfg, dict):
                    raw_reviewers = wave_cfg.get("reviewers")
                    if isinstance(raw_reviewers, list):
                        wave_reviewers = [str(item).strip() for item in raw_reviewers if str(item).strip()]
        if wave_reviewers:
            reviewers_by_name = {}
            for reviewer in reviewers:
                name = reviewer.get("name")
                if name:
                    reviewers_by_name[str(name)] = reviewer
            reviewers = [reviewers_by_name[name] for name in wave_reviewers if name in reviewers_by_name]
        if not reviewers:
            print(f"Wave '{review_wave}' produced an empty reviewer matrix", file=sys.stderr)
            sys.exit(1)

    matrix = []
    names = []
    for r in reviewers:
        name = r.get("name")
        perspective = r.get("perspective")
        if name and perspective:
            desc = r.get("description")
            role, tagline = split_description(desc)
            label = role or str(perspective).replace("_", " ").title()
            codename = str(name).title() if str(name).isupper() else str(name)

            entry = {
                "reviewer": name,
                "perspective": perspective,
                "reviewer_label": label,
                "reviewer_codename": codename,
            }
            model_tier = os.getenv("MODEL_TIER", "").strip().lower()
            if model_tier:
                entry["model_tier"] = model_tier
            if review_wave:
                entry["wave"] = review_wave
                entry["model_wave"] = review_wave
            if isinstance(desc, str) and desc.strip():
                entry["reviewer_description"] = desc.strip()
            if tagline:
                entry["reviewer_tagline"] = tagline

            matrix.append(entry)
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
