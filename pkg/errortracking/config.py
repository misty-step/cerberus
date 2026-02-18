"""Configuration objects for error tracking sources and aggregation behavior."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SUPPORTED_LOG_FORMATS = {"plain", "json"}


def _coerce_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _coerce_optional_int(value: Any, field_name: str, *, allow_none: bool = True) -> int | None:
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{field_name} must be an integer")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return value


def _coerce_positive_int(value: Any, field_name: str, default: int) -> int:
    parsed = _coerce_optional_int(value, field_name, allow_none=True)
    if parsed is None:
        return default
    return parsed


def _coerce_optional_float(value: Any, field_name: str, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a number")
    as_float = float(value)
    if as_float <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return as_float


def _coerce_patterns(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("errorPatterns must be an array of strings")
    patterns = []
    for item in value:
        patterns.append(_coerce_str(item, "errorPatterns item"))
    if not patterns:
        raise ValueError("errorPatterns cannot be empty")
    return tuple(dict.fromkeys(patterns))


@dataclass(frozen=True)
class ErrorSourceConfig:
    """Configuration for one structured or plain text log source."""

    source_id: str
    log_file: str
    log_format: str = "plain"
    error_patterns: tuple[str, ...] = ("ERROR", "CRITICAL", "EXCEPTION")
    poll_lines: int = 2000
    message_field: str = "message"
    stack_field: str = "stack"
    timestamp_field: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ErrorSourceConfig":
        source_id = _coerce_str(raw.get("id"), "id")
        log_file = _coerce_str(raw.get("path", raw.get("logFile", raw.get("file")),), "path")
        log_format = (raw.get("format") or raw.get("logFormat") or "plain").strip().lower()
        if log_format not in SUPPORTED_LOG_FORMATS:
            raise ValueError(f"format must be one of {sorted(SUPPORTED_LOG_FORMATS)}")
        patterns = _coerce_patterns(raw.get("errorPatterns", raw.get("patterns", ("ERROR", "CRITICAL", "EXCEPTION"))))
        poll_lines = _coerce_positive_int(
            raw.get("pollLines", raw.get("poll_lines")),
            "pollLines",
            2000,
        )
        message_field = _coerce_str(raw.get("messageField", raw.get("message_field", "message")), "messageField")
        stack_field = _coerce_str(raw.get("stackField", raw.get("stack_field", "stack")), "stackField")

        timestamp_field = raw.get("timestampField", raw.get("timestamp_field"))
        if timestamp_field is not None:
            timestamp_field = _coerce_str(timestamp_field, "timestampField")

        return cls(
            source_id=source_id,
            log_file=log_file,
            log_format=log_format,
            error_patterns=patterns,
            poll_lines=poll_lines,
            message_field=message_field,
            stack_field=stack_field,
            timestamp_field=timestamp_field,
        )


@dataclass(frozen=True)
class ErrorTrackingConfig:
    """Global behavior for grouping and alerting."""

    spike_window_seconds: int = 3600
    spike_multiplier: float = 2.5
    spike_min_count: int = 5
    trend_bucket_seconds: int = 300
    trend_buckets: int = 12

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None = None) -> "ErrorTrackingConfig":
        if raw is None:
            return cls()
        if not isinstance(raw, dict):
            raise ValueError("tracking config must be an object")

        return cls(
            spike_window_seconds=_coerce_positive_int(
                raw.get("spikeWindowSeconds", raw.get("spike_window_seconds")),
                "spikeWindowSeconds",
                3600,
            ),
            spike_multiplier=_coerce_optional_float(
                raw.get("spikeMultiplier", raw.get("spike_multiplier")),
                "spikeMultiplier",
                2.5,
            ),
            spike_min_count=_coerce_positive_int(
                raw.get("spikeMinCount", raw.get("spike_min_count")),
                "spikeMinCount",
                5,
            ),
            trend_bucket_seconds=_coerce_positive_int(
                raw.get("trendBucketSeconds", raw.get("trend_bucket_seconds")),
                "trendBucketSeconds",
                300,
            ),
            trend_buckets=_coerce_positive_int(
                raw.get("trendBuckets", raw.get("trend_buckets")),
                "trendBuckets",
                12,
            ),
        )
