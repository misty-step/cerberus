"""Shared runtime/API error taxonomy for reviewer execution and parsing."""

from __future__ import annotations

import re


_DECLARED_API_ERROR_TYPES = {
    "API_KEY_INVALID": "API_KEY_INVALID",
    "API_CREDITS_DEPLETED": "API_CREDITS_DEPLETED",
    "API_QUOTA_EXCEEDED": "API_CREDITS_DEPLETED",
    "RATE_LIMIT": "RATE_LIMIT",
    "SERVICE_UNAVAILABLE": "SERVICE_UNAVAILABLE",
    "API_ERROR": "API_ERROR",
}


def _declared_api_error_type(text: str) -> str | None:
    match = re.search(r"^\s*API Error:\s*([A-Z0-9_]+)", text, re.MULTILINE)
    if not match:
        return None
    return _DECLARED_API_ERROR_TYPES.get(match.group(1).upper())


def redact_runtime_error(text: str) -> str:
    redacted = text
    patterns = [
        (r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+", r"\1<redacted>"),
        (r"(?i)((?:api|access|secret|auth)[_-]?key\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
        (r"(?i)(token\s*[:=]\s*)[^\s,;]+", r"\1<redacted>"),
    ]
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted


def classify_api_error_text(text: str, *, runtime_error_class: str | None = None) -> str:
    declared = _declared_api_error_type(text)
    if declared:
        return declared

    lower = text.lower()

    if runtime_error_class == "rate_limit" or re.search(
        r"rate[ ._-]?limit|too many requests|retry-after|http[^0-9]*429|error[^0-9]*429",
        lower,
    ):
        return "RATE_LIMIT"

    if runtime_error_class == "server_5xx" or re.search(
        r"http[^0-9]*5[0-9]{2}|error[^0-9]*5[0-9]{2}|service[ ._-]?unavailable|temporarily[ ._-]?unavailable",
        lower,
    ):
        return "SERVICE_UNAVAILABLE"

    if re.search(
        r"api_key_invalid|incorrect_api_key|invalid_api_key|invalid[ ._-]?api[ ._-]?key|no[ ._-]?cookie[ ._-]?auth|"
        r"no credentials found|authentication failed|unauthorized|"
        r"missing authentication header|http[^0-9]*40[13]",
        lower,
    ):
        return "API_KEY_INVALID"

    if re.search(
        r"exceeded_current_quota|insufficient_quota|insufficient[ ._-]?credits|payment[ ._-]?required|"
        r"quota[ ._-]?exceeded|credits[ ._-]?depleted|credits[ ._-]?exhausted|402|\bbilling\b",
        lower,
    ):
        return "API_CREDITS_DEPLETED"

    return "API_ERROR"


def build_api_error_marker(
    *,
    stdout: str,
    stderr: str,
    models: list[str],
    runtime_error_class: str | None = None,
) -> str:
    error_msg = f"{stdout}\n{stderr}"
    sanitized_error = redact_runtime_error(error_msg)
    error_type = classify_api_error_text(
        sanitized_error,
        runtime_error_class=runtime_error_class,
    )
    models_tried = " ".join(models)
    return (
        f"API Error: {error_type}\n\n"
        "The API provider returned an error that prevents the review from completing:\n\n"
        f"{sanitized_error.strip()}\n\n"
        f"Models tried: {models_tried}\n"
        "Please check your API key and quota settings.\n"
    )
