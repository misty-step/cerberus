#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path


def fail(msg: str, code: int = 2) -> None:
    print(f"parse-review: {msg}", file=sys.stderr)
    sys.exit(code)


def read_input() -> str:
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).read_text()
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


def main() -> None:
    raw = read_input()
    json_block = extract_json_block(raw)
    try:
        obj = json.loads(json_block)
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON: {exc}")

    if not isinstance(obj, dict):
        fail("root must be object")

    validate(obj)
    print(json.dumps(obj, indent=2, sort_keys=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
