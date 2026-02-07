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
VERDICT_CONFIDENCE_MIN = 0.7
WARN_MINOR_THRESHOLD = 5
WARN_SAME_CATEGORY_MINOR_THRESHOLD = 3


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


def detect_api_error(text: str) -> tuple[bool, str]:
    """Detect if the text contains an API error. Returns (is_error, error_type)."""
    if "API Error:" in text:
        if "API_KEY_INVALID" in text or "401" in text or "authentication" in text.lower():
            return True, "API_KEY_INVALID"
        if "API_QUOTA_EXCEEDED" in text or "quota" in text.lower() or "billing" in text.lower():
            return True, "API_QUOTA_EXCEEDED"
        return True, "API_ERROR"
    return False, ""


def generate_skip_verdict(error_type: str, text: str) -> dict:
    """Generate a SKIP verdict for API errors."""
    return {
        "reviewer": "SYSTEM",
        "perspective": "error",
        "verdict": "SKIP",
        "confidence": 0.0,
        "summary": f"Review skipped due to API error: {error_type}",
        "findings": [
            {
                "severity": "info",
                "category": "api_error",
                "file": "N/A",
                "line": 0,
                "title": f"API Error: {error_type}",
                "description": text.strip(),
                "suggestion": "Check API key and quota settings.",
            }
        ],
        "stats": {
            "files_reviewed": 0,
            "files_with_issues": 0,
            "critical": 0,
            "major": 0,
            "minor": 0,
            "info": 1,
        },
    }


def extract_json_block(text: str) -> str | None:
    pattern = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
    matches = pattern.findall(text)
    if not matches:
        return None
    return matches[-1]


def looks_like_api_error(text: str) -> tuple[bool, str, str]:
    """Check if text looks like an API error without explicit API Error: marker.

    Returns (is_error, error_type, error_message)
    """
    # Common API error patterns
    error_patterns = [
        (r"401", "API_KEY_INVALID", "Invalid API key (401)"),
        (r"403", "API_KEY_INVALID", "Forbidden (403)"),
        (r"429", "RATE_LIMIT", "Rate limit exceeded (429)"),
        (r"503", "SERVICE_UNAVAILABLE", "Service unavailable (503)"),
        (r"exceeded_current_quota", "API_QUOTA_EXCEEDED", "API quota exceeded"),
        (r"incorrect_api_key", "API_KEY_INVALID", "Invalid API key"),
        (r"invalid_api_key", "API_KEY_INVALID", "Invalid API key"),
        (r"rate limit", "RATE_LIMIT", "Rate limit exceeded"),
        (r"quota exceeded", "API_QUOTA_EXCEEDED", "API quota exceeded"),
        (r"billing", "API_QUOTA_EXCEEDED", "Billing/quota error"),
        (r"authentication", "API_KEY_INVALID", "Authentication error"),
    ]

    for pattern, err_type, msg in error_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True, err_type, msg

    return False, "", ""


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

    if obj["verdict"] not in {"PASS", "WARN", "FAIL", "SKIP"}:
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
    if obj.get("verdict") == "SKIP":
        return

    findings = obj.get("findings", [])
    try:
        confidence = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    # Low-confidence reviews keep findings for visibility but do not gate merge.
    if confidence < VERDICT_CONFIDENCE_MIN:
        findings = []

    critical = sum(1 for f in findings if f.get("severity") == "critical")
    major = sum(1 for f in findings if f.get("severity") == "major")
    minor = sum(1 for f in findings if f.get("severity") == "minor")
    minor_by_category: dict[str, int] = {}
    for finding in findings:
        if finding.get("severity") != "minor":
            continue
        category = str(finding.get("category", "uncategorized")).strip() or "uncategorized"
        minor_by_category[category] = minor_by_category.get(category, 0) + 1
    same_category_minor_cluster = any(
        count >= WARN_SAME_CATEGORY_MINOR_THRESHOLD for count in minor_by_category.values()
    )

    if critical > 0 or major >= 2:
        computed = "FAIL"
    elif major == 1 or minor >= WARN_MINOR_THRESHOLD or same_category_minor_cluster:
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

    # Check for explicit API errors first (from run-reviewer.sh)
    is_api_error, error_type = detect_api_error(raw)
    if is_api_error:
        skip_verdict = generate_skip_verdict(error_type, raw)
        print(json.dumps(skip_verdict, indent=2, sort_keys=False))
        sys.exit(0)

    try:
        json_block = extract_json_block(raw)

        # If no JSON block found, check if it looks like an API error
        if json_block is None:
            is_err, err_type, err_msg = looks_like_api_error(raw)
            if is_err:
                skip_verdict = generate_skip_verdict(err_type, raw)
                print(json.dumps(skip_verdict, indent=2, sort_keys=False))
                sys.exit(0)
            fail("no ```json block found")

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
