#!/usr/bin/env python3
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import NoReturn

PARSE_FAILURE_PREFIX = "Review output could not be parsed: "
REVIEWER_NAME = "UNKNOWN"
PERSPECTIVE = "unknown"
RAW_INPUT = ""
VERDICT_CONFIDENCE_MIN = 0.7
WARN_MINOR_THRESHOLD = 5
WARN_SAME_CATEGORY_MINOR_THRESHOLD = 3

EVIDENCE_MAX_CHARS = 2000
CERBERUS_TMP = Path(os.environ.get("CERBERUS_TMP", tempfile.gettempdir()))


def resolve_reviewer(cli_reviewer: str | None) -> str:
    """Resolve reviewer."""
    reviewer = cli_reviewer or os.environ.get("REVIEWER_NAME") or "UNKNOWN"
    reviewer = reviewer.strip()
    return reviewer or "UNKNOWN"


def get_parse_failure_metadata() -> dict[str, list[str] | int | None]:
    """Read parse-failure retry metadata written by run-reviewer.sh.

    Returns dict with:
    - models: list of model names attempted for parse recovery
    - retry_count: number of retry attempts made
    """
    perspective = os.environ.get("PERSPECTIVE", "unknown")
    models_file = CERBERUS_TMP / f"{perspective}-parse-failure-models.txt"
    retries_file = CERBERUS_TMP / f"{perspective}-parse-failure-retries.txt"

    result: dict[str, list[str] | int | None] = {"models": None, "retry_count": None}

    if models_file.exists():
        try:
            models = [line.strip() for line in models_file.read_text().splitlines() if line.strip()]
            result["models"] = models if models else None
        except Exception:
            pass
        try:
            os.unlink(models_file)
        except OSError:
            pass

    if retries_file.exists():
        try:
            result["retry_count"] = int(retries_file.read_text().strip())
        except (ValueError, Exception):
            pass
        try:
            os.unlink(retries_file)
        except OSError:
            pass

    return result


def parse_args(argv: list[str]) -> tuple[str | None, str | None]:
    """Parse args."""
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
    # Check for explicit summary or verdict headers.
    for header in (r"## Summary", r"## Verdict:"):
        match = re.search(
            rf"{header}\s*\n(.*?)(?=\n##|\Z)", text, re.DOTALL,
        )
        if match:
            section = match.group(1).strip()
            if section:
                return section[:500]

    # Fallback: first 500 non-empty chars.
    stripped = text.strip()
    return stripped[:500] if stripped else ""


_AGENTIC_PREAMBLE_START_RE = re.compile(
    r"""
    ^\s*
    (?:[>\-*]\s*)?
    (?:
        i(?:'ll)\b
        |i\s+will\b
        |i\s+(?:am|'m)\s+going\s+to\b
        |i\s+need\s+to\b
        |now\s+i\b
        |next\s*,?\s+i\b
        |first\s*,?\s+i\b
        |then\s+i\b
        |let\s+me\b
        |let'?s\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_AGENTIC_PREAMBLE_VERB_RE = re.compile(
    r"\b(?:start|begin|read|review|examin|investigat|check|look|analyz|create|write|open|fetch|run|use|call|tool|step)\w*\b",
    re.IGNORECASE,
)

_FIRST_SENTENCE_RE = re.compile(r"(?s)^.*?(?:[.!?](?:\s+|\s*\n+)|\n+)")


def sanitize_raw_review(text: str) -> str:
    """Strip common agentic narration preambles from raw model output.

    Used only for preserving fallback/unparsed output (raw_review) in verdict JSON
    while removing tool-use/process narration.
    """
    sanitized = text.replace("\r\n", "\n").strip()
    # Normalize typographic apostrophes to ASCII to keep regex + matching simple.
    sanitized = sanitized.replace("\u2019", "'").replace("\u2018", "'")
    if not sanitized:
        return ""

    # Iteratively drop leading sentences/lines that look like "agentic plan"
    # narration. Keep the rest intact if it becomes substantive.
    for _ in range(100):
        match = _FIRST_SENTENCE_RE.match(sanitized)
        sentence = match.group(0) if match else sanitized
        if not _AGENTIC_PREAMBLE_START_RE.match(sentence):
            break
        if not _AGENTIC_PREAMBLE_VERB_RE.search(sentence):
            break
        sanitized = sanitized[len(sentence):].lstrip()
        if not sanitized:
            break

    sanitized = re.sub(r"\n{3,}", "\n\n", sanitized).strip()
    return sanitized


def write_fallback(
    reviewer: str, error: str, verdict: str = "FAIL", confidence: float = 0.0,
    summary: str | None = None, raw_review: str | None = None,
    findings: list[dict] | None = None,
) -> NoReturn:
    """Write fallback."""
    resolved_findings = findings if findings else []
    info_count = sum(1 for f in resolved_findings if f.get("severity") == "info")
    fallback = {
        "reviewer": reviewer,
        "perspective": PERSPECTIVE,
        "verdict": verdict,
        "confidence": confidence,
        "summary": summary or f"{PARSE_FAILURE_PREFIX}{error}",
        "findings": resolved_findings,
        "stats": {
            "files_reviewed": 0,
            "files_with_issues": 0,
            "critical": 0,
            "major": 0,
            "minor": 0,
            "info": info_count,
        },
    }
    if raw_review:
        sanitized_raw_review = sanitize_raw_review(raw_review)
        if sanitized_raw_review:
            fallback["raw_review"] = sanitized_raw_review[:50000]
    print(json.dumps(fallback, indent=2, sort_keys=False))
    sys.exit(0)


def fail(msg: str) -> NoReturn:
    """Fail."""
    print(f"parse-review: {msg}", file=sys.stderr)
    raw_text = RAW_INPUT.strip() if RAW_INPUT else None
    if is_scratchpad(RAW_INPUT):
        # Treat unstructured (non-JSON) reviews as SKIP.
        # A markdown "Verdict: FAIL" without machine-parseable findings is not actionable and is too flaky to gate merges.
        verdict = "SKIP"
        summary = "Partial review: reviewer output was unstructured (no JSON). Treating as SKIP; see workflow logs/artifacts for full output."
        write_fallback(REVIEWER_NAME, msg, verdict=verdict, confidence=0.3,
                       summary=summary, raw_review=raw_text or None,
                       findings=[{
                           "severity": "info",
                           "category": "parse-failure",
                           "file": "N/A",
                           "line": 0,
                           "title": "Review analysis available but not machine-parseable",
                           "description": "Reviewer produced a scratchpad review without structured JSON output. Raw output is preserved in workflow logs/artifacts.",
                           "suggestion": "No action needed; see the workflow run for the preserved raw output.",
                       }])
    write_fallback(REVIEWER_NAME, msg, verdict="SKIP", raw_review=raw_text or None)


def read_input(path: str | None) -> str:
    """Read input."""
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
    """Generate timeout skip verdict."""
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
    """Extract json block."""
    pattern = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
    matches = pattern.findall(text)
    if not matches:
        return None
    return matches[-1]


def extract_json_from_output(text: str) -> str | None:
    """Extract JSON from model output.

    Tries direct JSON parse first (structured-output path), then fenced-block extraction.
    This lets parse-review.py accept pre-extracted JSON without requiring ```json``` fences.
    """
    stripped = text.strip()
    if stripped.startswith("{"):
        return stripped
    return extract_json_block(text)


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
    # Inject known metadata fields before validation — models often omit these
    # even when the rest of the review is valid.
    """Validate."""
    if "reviewer" not in obj:
        obj["reviewer"] = REVIEWER_NAME
    if "perspective" not in obj:
        obj["perspective"] = PERSPECTIVE

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
        ]:
            if fkey not in finding:
                fail(f"finding {idx} missing field: {fkey}")
        # suggestion is optional — backfill so downstream always has the key
        if "suggestion" not in finding:
            finding["suggestion"] = ""
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


def validate_and_correct_stats(obj: dict) -> None:
    """Validate LLM-reported stats against actual findings; correct if mismatched.

    Replaces hallucinated severity counts with programmatically counted values.
    Adds _stats_discrepancy to the output when a mismatch is detected.
    """
    findings = obj.get("findings", [])
    if not isinstance(findings, list):
        return

    stats = obj.get("stats")
    if not isinstance(stats, dict):
        return

    actual_critical = sum(1 for f in findings if isinstance(f, dict) and f.get("severity") == "critical")
    actual_major = sum(1 for f in findings if isinstance(f, dict) and f.get("severity") == "major")
    actual_minor = sum(1 for f in findings if isinstance(f, dict) and f.get("severity") == "minor")
    actual_info = sum(1 for f in findings if isinstance(f, dict) and f.get("severity") == "info")

    unique_files = {
        str(f.get("file", "")).strip()
        for f in findings
        if isinstance(f, dict) and str(f.get("file", "")).strip() not in {"", "N/A"}
    }
    actual_files_with_issues = len(unique_files)

    reported = {
        "critical": stats.get("critical", 0),
        "major": stats.get("major", 0),
        "minor": stats.get("minor", 0),
        "info": stats.get("info", 0),
        "files_with_issues": stats.get("files_with_issues", 0),
    }
    actual = {
        "critical": actual_critical,
        "major": actual_major,
        "minor": actual_minor,
        "info": actual_info,
        "files_with_issues": actual_files_with_issues,
    }

    if reported != actual:
        print(
            f"parse-review: stats discrepancy detected — reported: {reported}, actual: {actual}",
            file=sys.stderr,
        )
        stats["critical"] = actual_critical
        stats["major"] = actual_major
        stats["minor"] = actual_minor
        stats["info"] = actual_info
        stats["files_with_issues"] = actual_files_with_issues
        obj["_stats_discrepancy"] = {
            "reported": reported,
            "actual": actual,
            "discrepancy": True,
        }


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
    "no such version",
]


def downgrade_stale_knowledge_findings(obj: dict) -> None:
    """Downgrade stale knowledge findings."""
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


def _unwrap_fenced_code_block(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < 2:
        return stripped
    if not lines[0].startswith("```"):
        return stripped
    if lines[-1].strip() != "```":
        return stripped
    return "\n".join(lines[1:-1]).strip("\n")


def _normalize_evidence(text: str) -> str:
    evidence = text.replace("\r\n", "\n").strip()
    evidence = _unwrap_fenced_code_block(evidence)

    # If the model pasted diff lines, strip leading +/-/space markers.
    lines = evidence.splitlines()
    if lines:
        looks_like_diff = (
            all((ln.startswith(("+", "-", " ")) and not ln.startswith(("+++ ", "--- "))) or ln == "" for ln in lines)
            and any(ln.startswith(("+", "-")) for ln in lines if ln)
        )
        if looks_like_diff:
            lines = [ln[1:] if ln.startswith(("+", "-", " ")) else ln for ln in lines]
            evidence = "\n".join(lines).strip("\n")

    return evidence


def _truncate_evidence_for_output(evidence: str) -> str:
    if len(evidence) > EVIDENCE_MAX_CHARS:
        return evidence[:EVIDENCE_MAX_CHARS] + "..."
    return evidence


def normalize_evidence_fields(obj: dict) -> None:
    """Strip diff markers, unfence code blocks, truncate evidence for display."""
    for finding in obj.get("findings", []):
        if not isinstance(finding, dict):
            continue
        evidence_raw = finding.get("evidence")
        if not isinstance(evidence_raw, str) or not evidence_raw.strip():
            continue
        evidence = _normalize_evidence(evidence_raw)
        if evidence:
            finding["evidence"] = _truncate_evidence_for_output(evidence)
        else:
            finding.pop("evidence", None)


def main() -> None:
    """Main."""
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
        json_block = extract_json_from_output(raw)

        # If no JSON block found, check if it looks like an API error
        if json_block is None:
            is_err, err_type, err_msg = looks_like_api_error(raw)
            if is_err:
                skip_verdict = generate_skip_verdict(err_type, raw)
                print(json.dumps(skip_verdict, indent=2, sort_keys=False))
                sys.exit(0)

            print("parse-review: no ```json block found", file=sys.stderr)

            raw_text = raw.strip()
            sanitized_text = sanitize_raw_review(raw_text)

            # The model sometimes exits 0 but produces empty/non-JSON output.
            # Check if it's a scratchpad (has investigation notes or verdict header)
            # and extract what we can before falling back.
            if is_scratchpad(raw):
                verdict = "SKIP"
                summary = "Partial review: reviewer output was unstructured (no JSON). Treating as SKIP; see workflow logs/artifacts for full output."
                write_fallback(REVIEWER_NAME, "no ```json block found",
                               verdict=verdict, confidence=0.3,
                               summary=summary, raw_review=raw_text or None,
                               findings=[{
                                   "severity": "info",
                                   "category": "parse-failure",
                                   "file": "N/A",
                                   "line": 0,
                                   "title": "Review analysis available but not machine-parseable",
                                   "description": "Reviewer produced a scratchpad review without structured JSON output. Raw output is preserved in workflow logs/artifacts.",
                                   "suggestion": "No action needed; see the workflow run for the preserved raw output.",
                               }])

            # Substantive raw text exists — upgrade to WARN so the review is visible.
            if len(sanitized_text) > 500:
                summary = "Partial review: reviewer output was unstructured (no JSON). See workflow logs/artifacts for full output."
                write_fallback(REVIEWER_NAME, "no ```json block found",
                               verdict="WARN", confidence=0.3,
                               summary=summary,
                               raw_review=sanitized_text,
                               findings=[{
                                   "severity": "info",
                                   "category": "parse-failure",
                                   "file": "N/A",
                                   "line": 0,
                                   "title": "Review analysis available but not machine-parseable",
                                   "description": "Reviewer produced substantive output without structured JSON. Raw output is preserved in workflow logs/artifacts.",
                                   "suggestion": "No action needed; see the workflow run for the preserved raw output.",
                               }])

            # Not a scratchpad and not substantive — SKIP (non-blocking).
            # Include parse-failure retry metadata if available.
            pf_meta = get_parse_failure_metadata()
            summary_parts = [f"{PARSE_FAILURE_PREFIX}no ```json block found"]
            if pf_meta.get("retry_count") is not None:
                summary_parts.append(f"({pf_meta['retry_count']} parse-recovery retries attempted)")
            if pf_meta.get("models"):
                models_str = ", ".join(pf_meta["models"])
                summary_parts.append(f"Models tried: {models_str}")
            skip_summary = " ".join(summary_parts)

            # Only attach a finding when retries were actually attempted.
            skip_findings: list[dict[str, object]] | None = None
            if pf_meta.get("retry_count") is not None:
                skip_findings = [{
                    "severity": "info",
                    "category": "parse-failure",
                    "file": "N/A",
                    "line": 0,
                    "title": "Review output could not be parsed",
                    "description": "Reviewer produced output without a structured JSON block after retries. See raw review for details.",
                    "suggestion": "No action needed; review content is preserved in the raw output section.",
                }]

            write_fallback(
                REVIEWER_NAME,
                "no ```json block found",
                verdict="SKIP",
                confidence=0.0,
                summary=skip_summary,
                raw_review=sanitized_text if sanitized_text else None,
                findings=skip_findings,
            )

        try:
            obj = json.loads(json_block)
        except json.JSONDecodeError as exc:
            fail(f"invalid JSON: {exc}")

        if not isinstance(obj, dict):
            fail("root must be object")

        validate(obj)
        validate_and_correct_stats(obj)
        normalize_evidence_fields(obj)
        downgrade_stale_knowledge_findings(obj)
        enforce_verdict_consistency(obj)
    except Exception as exc:
        fail(f"unexpected error: {exc}")

    print(json.dumps(obj, indent=2, sort_keys=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
