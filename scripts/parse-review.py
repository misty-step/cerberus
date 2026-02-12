#!/usr/bin/env python3
import json
import os
import re
import sys
from pathlib import Path
from typing import NoReturn

PARSE_FAILURE_PREFIX = "Review output could not be parsed: "
REVIEWER_NAME = "UNKNOWN"
PERSPECTIVE = "unknown"
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


def extract_review_summary(text: str) -> str:
    """Extract a meaningful summary from unstructured review text."""
    # Check for explicit summary or verdict headers
    for header in (r"## Summary", r"## Verdict:"):
        match = re.search(
            rf"{header}\s*\n(.*?)(?=\n##|\Z)", text, re.DOTALL,
        )
        if match:
            section = match.group(1).strip()
            if section:
                return section[:500]

    # Fallback: first 500 non-empty chars
    stripped = text.strip()
    return stripped[:500] if stripped else ""


def extract_notes_summary(text: str, max_len: int = 10000) -> str:
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
    summary: str | None = None, raw_review: str | None = None,
) -> NoReturn:
    fallback = {
        "reviewer": reviewer,
        "perspective": PERSPECTIVE,
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
    if raw_review:
        fallback["raw_review"] = raw_review[:50000]
    print(json.dumps(fallback, indent=2, sort_keys=False))
    sys.exit(0)


def fail(msg: str) -> NoReturn:
    print(f"parse-review: {msg}", file=sys.stderr)
    raw_text = RAW_INPUT.strip() if RAW_INPUT else None
    if is_scratchpad(RAW_INPUT):
        md_verdict = extract_verdict_from_markdown(RAW_INPUT)
        verdict = md_verdict or "WARN"
        notes = extract_notes_summary(RAW_INPUT)
        summary = f"Partial review (investigation notes follow). {notes}" if notes else "Partial review timed out before completion."
        write_fallback(REVIEWER_NAME, msg, verdict=verdict, confidence=0.3,
                       summary=summary, raw_review=raw_text or None)
    write_fallback(REVIEWER_NAME, msg, raw_review=raw_text or None)


def read_input(path: str | None) -> str:
    if path:
        return Path(path).read_text()
    return sys.stdin.read()


def detect_api_error(text: str) -> tuple[bool, str]:
    """Detect if the text contains an API error. Returns (is_error, error_type)."""
    if "API Error:" in text:
        if "API_KEY_INVALID" in text or "authentication" in text.lower():
            return True, "API_KEY_INVALID"
        if "API_CREDITS_DEPLETED" in text or "API_QUOTA_EXCEEDED" in text:
            return True, "API_CREDITS_DEPLETED"
        if "402" in text or "payment required" in text.lower():
            return True, "API_CREDITS_DEPLETED"
        if "quota" in text.lower() or "billing" in text.lower():
            return True, "API_CREDITS_DEPLETED"
        return True, "API_ERROR"
    return False, ""


def detect_timeout(text: str) -> tuple[bool, int | None, str, str]:
    """Detect explicit timeout markers from run-reviewer.sh output.

    Returns (is_timeout, timeout_seconds, files_in_diff, fast_path_status).
    """
    timeout_match = re.search(r"Review Timeout:\s*timeout after\s*(\d+)s", text, re.IGNORECASE)
    if not timeout_match:
        generic_timeout_match = re.search(r"timeout after\s*(\d+)s", text, re.IGNORECASE)
        if not generic_timeout_match:
            return False, None, "", ""
        timeout_match = generic_timeout_match

    timeout_seconds = int(timeout_match.group(1))

    # Extract enriched metadata from timeout marker.
    files_match = re.search(
        r"^Files in diff:\s*(.*?)(?=^Next steps:|\Z)", text, re.DOTALL | re.MULTILINE,
    )
    files_in_diff = files_match.group(1).strip() if files_match else ""

    fp_match = re.search(r"^Fast-path:\s*(.+)$", text, re.MULTILINE)
    fast_path_status = fp_match.group(1).strip() if fp_match else ""

    return True, timeout_seconds, files_in_diff, fast_path_status


def generate_skip_verdict(error_type: str, text: str) -> dict:
    """Generate a SKIP verdict for API errors."""
    if error_type == "API_CREDITS_DEPLETED":
        summary = f"Review skipped: API credits depleted ({error_type})"
        suggestion = "Top up API credits or configure a fallback provider."
    else:
        summary = f"Review skipped due to API error: {error_type}"
        suggestion = "Check API key and quota settings."

    return {
        "reviewer": REVIEWER_NAME,
        "perspective": PERSPECTIVE,
        "verdict": "SKIP",
        "confidence": 0.0,
        "summary": summary,
        "findings": [
            {
                "severity": "info",
                "category": "api_error",
                "file": "N/A",
                "line": 0,
                "title": f"API Error: {error_type}",
                "description": text.strip(),
                "suggestion": suggestion,
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


def generate_timeout_skip_verdict(
    reviewer: str,
    timeout_seconds: int | None,
    files_in_diff: str = "",
    fast_path_status: str = "",
) -> dict:
    timeout_suffix = f" after {timeout_seconds}s" if timeout_seconds is not None else ""

    # Build an informative description with available diagnostics.
    desc_parts = ["Reviewer exceeded the configured runtime limit before completing."]
    if files_in_diff:
        desc_parts.append(f"Files in diff: {files_in_diff}")
    if fast_path_status:
        desc_parts.append(f"Fast-path fallback: {fast_path_status}")
    description = " ".join(desc_parts)

    suggestion_parts = []
    if fast_path_status.startswith("yes") or fast_path_status.startswith("attempted"):
        suggestion_parts.append("Model provider may be stalled — check provider status.")
    suggestion_parts.append("Increase timeout, reduce diff size, or try a faster model.")
    suggestion = " ".join(suggestion_parts)

    verdict: dict = {
        "reviewer": reviewer,
        "perspective": PERSPECTIVE,
        "verdict": "SKIP",
        "confidence": 0.0,
        "summary": f"Review skipped due to timeout{timeout_suffix}.",
        "findings": [
            {
                "severity": "info",
                "category": "timeout",
                "file": "N/A",
                "line": 0,
                "title": f"Reviewer timeout{timeout_suffix}",
                "description": description,
                "suggestion": suggestion,
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
    if files_in_diff:
        verdict["files_in_diff"] = [f.strip() for f in files_in_diff.split("\n") if f.strip()]
    return verdict


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
        (r"402", "API_CREDITS_DEPLETED", "Payment required / credits depleted (402)"),
        (r"403", "API_KEY_INVALID", "Forbidden (403)"),
        (r"429", "RATE_LIMIT", "Rate limit exceeded (429)"),
        (r"503", "SERVICE_UNAVAILABLE", "Service unavailable (503)"),
        (r"payment required", "API_CREDITS_DEPLETED", "Payment required / credits depleted"),
        (r"exceeded_current_quota", "API_CREDITS_DEPLETED", "API quota exceeded"),
        (r"insufficient_quota", "API_CREDITS_DEPLETED", "Insufficient quota"),
        (r"incorrect_api_key", "API_KEY_INVALID", "Invalid API key"),
        (r"invalid_api_key", "API_KEY_INVALID", "Invalid API key"),
        (r"rate limit", "RATE_LIMIT", "Rate limit exceeded"),
        (r"quota exceeded", "API_CREDITS_DEPLETED", "API quota exceeded"),
        (r"billing", "API_CREDITS_DEPLETED", "Billing/quota error"),
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


def _has_version_reference(text: str) -> bool:
    """Check if text contains a numeric version pattern (e.g., 1.25, v3, 24.x)."""
    import re
    return bool(re.search(r'\d+\.\d+|\bv\d+\b|\d+\.x\b', text))


def _is_version_category(category: str) -> bool:
    """Check if category indicates a version/dependency topic (normalized)."""
    normalized = category.replace("-", " ").replace("_", " ")
    return any(
        marker in normalized
        for marker in ("version conflict", "version mismatch",
                       "dependency conflict", "dependency mismatch")
    )


# Long context terms are unambiguous; short ones ("go", "node") need a version
# number nearby to avoid matching ordinary English.
_LONG_CONTEXT_TERMS = [
    "golang", "python", "nodejs", "javascript", "typescript", "kotlin",
    "swift", "ruby", "rails", "rust", "php", "dotnet", ".net",
    "next.js", "nextjs", "react", "vue", "angular", "django", "flask",
    "fastapi",
]
_SHORT_CONTEXT_TERMS = ["go", "node", "java"]

_RELEASE_CLAIM_PATTERNS = [
    "is not released",
    "has not been released",
    "not yet released",
    "latest stable is",
    "latest version is",
    "no such version",
]


def downgrade_stale_knowledge_findings(obj: dict) -> None:
    findings = obj.get("findings", [])
    if not isinstance(findings, list):
        return

    downgraded = 0
    for finding in findings:
        if not isinstance(finding, dict):
            continue

        text = " ".join(
            str(finding.get(key, "")) for key in ("title", "description", "suggestion")
        ).lower()
        category = str(finding.get("category", "")).lower()

        has_version_num = _has_version_reference(text)

        # "does not exist" requires BOTH a context term AND a version reference
        # to avoid matching "the go binary does not exist"
        has_does_not_exist_claim = "does not exist" in text and (
            "version" in text
            or any(term in text for term in _LONG_CONTEXT_TERMS)
            or (any(term in text for term in _SHORT_CONTEXT_TERMS) and has_version_num)
        )

        # Release claims also require a version reference for safety
        has_release_claim = (
            any(pattern in text for pattern in _RELEASE_CLAIM_PATTERNS)
            and has_version_num
        )

        has_invalid_version_claim = "invalid version" in text
        is_version_conflict = _is_version_category(category)

        should_downgrade = (
            has_does_not_exist_claim
            or has_release_claim
            or (has_invalid_version_claim and not is_version_conflict)
        )
        if not should_downgrade:
            continue

        finding["severity"] = "info"
        finding["_stale_knowledge_downgraded"] = True
        title = str(finding.get("title", ""))
        if not title.startswith("[stale-knowledge] "):
            finding["title"] = f"[stale-knowledge] {title}"
        downgraded += 1

    # Recompute stats to stay consistent with modified severities
    if downgraded > 0:
        stats = obj.get("stats")
        if isinstance(stats, dict):
            for sev in ("critical", "major", "minor", "info"):
                stats[sev] = sum(
                    1 for f in findings
                    if isinstance(f, dict) and f.get("severity") == sev
                )


def main() -> None:
    global REVIEWER_NAME, PERSPECTIVE, RAW_INPUT

    PERSPECTIVE = os.environ.get("PERSPECTIVE", "unknown")

    try:
        input_path, reviewer = parse_args(sys.argv[1:])
    except ValueError as exc:
        REVIEWER_NAME = resolve_reviewer(None)
        fail(str(exc))

    REVIEWER_NAME = resolve_reviewer(reviewer)

    try:
        raw = read_input(input_path)
    except Exception as exc:
        # If we can't read the parse input file, this is almost always a prior-step failure
        # (e.g., the reviewer never produced output). Treat as SKIP so we don't block the PR
        # with a misleading maintainability/correctness failure.
        print(f"parse-review: unable to read input: {exc}", file=sys.stderr)
        write_fallback(
            REVIEWER_NAME,
            f"unable to read input: {exc}",
            verdict="SKIP",
            confidence=0.0,
            summary=f"{PARSE_FAILURE_PREFIX}unable to read input: {exc}",
        )

    RAW_INPUT = raw

    # Check for explicit timeout markers first (from run-reviewer.sh)
    is_timeout, timeout_seconds, files_in_diff, fast_path_status = detect_timeout(raw)
    if is_timeout:
        timeout_verdict = generate_timeout_skip_verdict(
            REVIEWER_NAME, timeout_seconds, files_in_diff, fast_path_status,
        )
        print(json.dumps(timeout_verdict, indent=2, sort_keys=False))
        sys.exit(0)

    # Check for explicit API errors next (from run-reviewer.sh)
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

            print("parse-review: no ```json block found", file=sys.stderr)

            raw_text = raw.strip()

            # The model sometimes exits 0 but produces empty/non-JSON output.
            # Check if it's a scratchpad (has investigation notes or verdict header)
            # and extract what we can before falling back.
            if is_scratchpad(raw):
                md_verdict = extract_verdict_from_markdown(raw)
                verdict = md_verdict or "WARN"
                notes = extract_notes_summary(raw)
                summary = f"Partial review (investigation notes follow). {notes}" if notes else "Partial review timed out before completion."
                write_fallback(REVIEWER_NAME, "no ```json block found",
                               verdict=verdict, confidence=0.3,
                               summary=summary, raw_review=raw_text or None)

            # Substantive raw text exists — upgrade to WARN so the review is visible.
            if len(raw_text) > 500:
                summary = extract_review_summary(raw_text)
                write_fallback(REVIEWER_NAME, "no ```json block found",
                               verdict="WARN", confidence=0.3,
                               summary=summary or f"{PARSE_FAILURE_PREFIX}no ```json block found",
                               raw_review=raw_text)

            # Not a scratchpad and not substantive — SKIP (non-blocking).
            write_fallback(
                REVIEWER_NAME,
                "no ```json block found",
                verdict="SKIP",
                confidence=0.0,
                summary=f"{PARSE_FAILURE_PREFIX}no ```json block found",
                raw_review=raw_text if raw_text else None,
            )

        try:
            obj = json.loads(json_block)
        except json.JSONDecodeError as exc:
            fail(f"invalid JSON: {exc}")

        if not isinstance(obj, dict):
            fail("root must be object")

        validate(obj)
        downgrade_stale_knowledge_findings(obj)
        enforce_verdict_consistency(obj)
    except Exception as exc:
        fail(f"unexpected error: {exc}")

    print(json.dumps(obj, indent=2, sort_keys=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
