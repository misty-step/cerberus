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

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib.defaults_config import ConfigError, DefaultsConfig, Reviewer, load_defaults_config  # noqa: E402


TMP_MATRIX_OUTPUT = Path("/tmp/matrix-output.json")
TMP_MATRIX_COUNT = Path("/tmp/matrix-count.txt")
TMP_MATRIX_NAMES = Path("/tmp/matrix-names.txt")


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


def _load_config(path: str) -> DefaultsConfig:
    try:
        return load_defaults_config(Path(path))
    except ConfigError as exc:
        print(f"Config load error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _reviewers_for_wave(cfg: DefaultsConfig, review_wave: str) -> list[Reviewer]:
    if not review_wave:
        return list(cfg.reviewers)

    definition = cfg.waves.definitions.get(review_wave)
    if definition is None:
        print(f"Unknown review wave '{review_wave}'", file=sys.stderr)
        raise SystemExit(1)

    reviewers_by_name = {reviewer.name: reviewer for reviewer in cfg.reviewers}
    reviewers = [
        reviewers_by_name[name]
        for name in definition.reviewers
        if name in reviewers_by_name
    ]
    if not reviewers:
        print(f"Wave '{review_wave}' produced an empty reviewer matrix", file=sys.stderr)
        raise SystemExit(1)
    return reviewers


def _normalize_panel_filter(raw: str) -> set[str]:
    if not raw.strip():
        return set()
    try:
        panel = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Invalid PANEL_FILTER JSON: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if not isinstance(panel, list):
        print("Invalid PANEL_FILTER JSON: expected array", file=sys.stderr)
        raise SystemExit(1)
    return {str(item) for item in panel}


def _build_entry(reviewer: Reviewer, *, model_tier: str, review_wave: str) -> dict[str, Any]:
    role, tagline = split_description(reviewer.description)
    label = role or reviewer.perspective.replace("_", " ").title()
    codename = reviewer.name.title() if reviewer.name.isupper() else reviewer.name

    entry: dict[str, Any] = {
        "reviewer": reviewer.name,
        "perspective": reviewer.perspective,
        "reviewer_label": label,
        "reviewer_codename": codename,
    }
    if model_tier:
        entry["model_tier"] = model_tier
    if review_wave:
        entry["wave"] = review_wave
        entry["model_wave"] = review_wave
    if reviewer.description:
        entry["reviewer_description"] = reviewer.description
    if tagline:
        entry["reviewer_tagline"] = tagline
    return entry


def generate_matrix(config_path: str) -> None:
    """Generate matrix."""
    cfg = _load_config(config_path)
    review_wave = os.getenv("REVIEW_WAVE", "").strip().lower()
    model_tier = os.getenv("MODEL_TIER", "").strip().lower()
    panel_filter = _normalize_panel_filter(os.getenv("PANEL_FILTER", ""))

    reviewers = _reviewers_for_wave(cfg, review_wave)
    matrix = [
        _build_entry(reviewer, model_tier=model_tier, review_wave=review_wave)
        for reviewer in reviewers
    ]

    if panel_filter:
        filtered = [entry for entry in matrix if entry["perspective"] in panel_filter]
        if filtered:
            matrix = filtered
        else:
            print(
                "::warning::Panel filter matched no reviewers; using full matrix",
                file=sys.stderr,
            )

    matrix_json = json.dumps({"include": matrix})
    count = str(len(matrix))
    names_csv = ",".join(entry["reviewer"] for entry in matrix)

    TMP_MATRIX_OUTPUT.write_text(matrix_json)
    TMP_MATRIX_COUNT.write_text(count)
    TMP_MATRIX_NAMES.write_text(names_csv)

    print(matrix_json)
    print(count)
    print(names_csv)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <config-path>", file=sys.stderr)
        sys.exit(1)
    generate_matrix(sys.argv[1])
