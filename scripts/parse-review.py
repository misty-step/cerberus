#!/usr/bin/env python3
import json
import os
import re
import sys
from pathlib import Path
from typing import NoReturn

PARSE_FAILURE_PREFIX = "Review output could not be parsed: "
REVIEWER_NAME = "UNKNOWN"
RAW_INPUT = ""


def resolve_reviewer(cli_reviewer: str | None) -> str:
    reviewer = cli_reviewer or os.environ.get("REVIEWER_NAME") or "UNKNOWN"
    reviewer = reviewer.strip()
    return reviewer or "UNKNOWN"


def parse_args(argv: list[str]) -> tuple[str | None, str | None]:
    input_path = None
    reviewer = None
    idx = 0
    while idx < len(argv):
        arg = argv[idx]
        if arg == "--reviewer":
            if idx + 1 >= len(argv):
                raise ValueError("--reviewer requires a value")
            reviewer = argv[idx + 1]
            idx += 2
            continue
        if arg.startswith("--reviewer="):
            reviewer = arg.split("=", 1)[1]
            idx += 1
            continue
        if arg.startswith("-"):
            raise ValueError(f"unknown argument: {arg}")
        if input_path is not None:
            raise ValueError("too many positional arguments")
        input_path = arg
        idx += 1
    return input_path, reviewer


def extract_verdict_from_markdown(text: str) -> str | None:
    """Extract verdict from markdown header when JSON block is missing."""
    match = re.search(r"^## Verdict:\s*(PASS|WARN|FAIL)", text, re.MULTILINE)
    return match.group(1) if match else None


def is_scratchpad(text: str) -> bool:
    """Check if text looks like a scratchpad review document."""
    return "## Investigation Notes" in text or "## Verdict:" in text


def extract_notes_summary(text: str, max_len: int = 200) -> str:
    """Extract investigation notes for inclusion in partial review summary."""
    match = re.search(
        r"## Investigation Notes\s*\n(.*?)(?=\n##|\Z)", text, re.DOTALL
    )
    if not match:
        return ""
    notes = match.group(1).strip()
    if len(notes) > max_len:
        notes = notes[:max_len] + "..."
    return notes


def write_fallback(
    reviewer: str, error: str, verdict: str = "FAIL", confidence: float = 0.0,
    summary: str | None = None,
) -> NoReturn:
    fallback = {
        "reviewer": reviewer,
        "perspective": "unknown",
        "verdict": verdict,
        "confidence": confidence,
        "summary": summary or f"{PARSE_FAILURE_PREFIX}{error}",
        "findings": [],
        "stats": {
            "files_reviewed": 0,
            "files_with_issues": 0,
            "critical": 0,
            "major": 0,
            "minor": 0,
            "info": 0,
        },
    }
    print(json.dumps(fallback, indent=2, sort_keys=False))
    sys.exit(0)


def fail(msg: str) -> NoReturn:
    print(f"parse-review: {msg}", file=sys.stderr)
    if is_scratchpad(RAW_INPUT):
        md_verdict = extract_verdict_from_markdown(RAW_INPUT)
        verdict = md_verdict or "WARN"
        notes = extract_notes_summary(RAW_INPUT)
        summary = f"Partial review (investigation notes follow). {notes}" if notes else "Partial review timed out before completion."
        write_fallback(REVIEWER_NAME, msg, verdict=verdict, confidence=0.3, summary=summary)
    write_fallback(REVIEWER_NAME, msg)


def read_input(path: str | None) -> str:
    if path:
        return Path(path).read_text()
    return sys.stdin.read()


def extract_json_block(text: str) -> str:
    pattern = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
    matches = pattern.findall(text)
    if not matches:
        fail("no ```json block found")
    return matches[-1]


def validate(obj: dict) -> None:
    required_root = [
        "reviewer",
        "perspective",
        "verdict",
        "confidence",
        "summary",
        "findings",
        "stats",
    ]
    for key in required_root:
        if key not in obj:
            fail(f"missing root field: {key}")

    if obj["verdict"] not in {"PASS", "WARN", "FAIL"}:
        fail("invalid verdict")

    if not isinstance(obj["confidence"], (int, float)):
        fail("confidence must be number")
    if obj["confidence"] < 0 or obj["confidence"] > 1:
        fail("confidence out of range")

    if not isinstance(obj["findings"], list):
        fail("findings must be a list")

    for idx, finding in enumerate(obj["findings"]):
        if not isinstance(finding, dict):
            fail(f"finding {idx} not object")
        for fkey in [
            "severity",
            "category",
            "file",
            "line",
            "title",
            "description",
            "suggestion",
        ]:
            if fkey not in finding:
                fail(f"finding {idx} missing field: {fkey}")
        if finding["severity"] not in {"critical", "major", "minor", "info"}:
            fail(f"finding {idx} invalid severity")
        if not isinstance(finding["line"], int):
            try:
                finding["line"] = int(finding["line"])
            except Exception as exc:
                fail(f"finding {idx} line not int: {exc}")

    stats = obj["stats"]
    for skey in [
        "files_reviewed",
        "files_with_issues",
        "critical",
        "major",
        "minor",
        "info",
    ]:
        if skey not in stats:
            fail(f"stats missing field: {skey}")
        if not isinstance(stats[skey], int):
            fail(f"stats field not int: {skey}")


def enforce_verdict_consistency(obj: dict) -> None:
    """Recompute verdict from findings to prevent LLM verdict manipulation."""
    findings = obj.get("findings", [])
    critical = sum(1 for f in findings if f.get("severity") == "critical")
    major = sum(1 for f in findings if f.get("severity") == "major")
    minor = sum(1 for f in findings if f.get("severity") == "minor")

    if critical > 0 or major >= 2:
        computed = "FAIL"
    elif major == 1 or minor >= 3:
        computed = "WARN"
    else:
        computed = "PASS"

    if obj["verdict"] != computed:
        obj["verdict"] = computed


def main() -> None:
    global REVIEWER_NAME, RAW_INPUT

    try:
        input_path, reviewer = parse_args(sys.argv[1:])
    except ValueError as exc:
        REVIEWER_NAME = resolve_reviewer(None)
        fail(str(exc))

    REVIEWER_NAME = resolve_reviewer(reviewer)

    try:
        raw = read_input(input_path)
    except Exception as exc:
        fail(f"unable to read input: {exc}")

    RAW_INPUT = raw

    try:
        json_block = extract_json_block(raw)
        try:
            obj = json.loads(json_block)
        except json.JSONDecodeError as exc:
            fail(f"invalid JSON: {exc}")

        if not isinstance(obj, dict):
            fail("root must be object")

        validate(obj)
        enforce_verdict_consistency(obj)
    except Exception as exc:
        fail(f"unexpected error: {exc}")

    print(json.dumps(obj, indent=2, sort_keys=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
