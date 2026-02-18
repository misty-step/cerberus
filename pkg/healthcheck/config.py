from __future__ import annotations

from dataclasses import dataclass
from typing import Any


HTTP_METHODS = {"GET", "POST"}
DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_TIMEOUT_SECONDS = 10


def _coerce_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_optional_int(value: Any, field_name: str, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if isinstance(value, int):
        if value <= 0:
            raise ValueError(f"{field_name} must be greater than zero")
        return value
    raise ValueError(f"{field_name} must be an integer")


def _coerce_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _coerce_strict_status(value: Any) -> int:
    if not isinstance(value, int):
        raise ValueError("expectedStatus must be an integer")
    if value < 100 or value > 599:
        raise ValueError("expectedStatus must be a valid HTTP status code")
    return value


@dataclass(frozen=True)
class HealthCheckConfig:
    """Configuration for a single health check."""

    id: str
    url: str
    http_method: str = "GET"
    expected_status: int = 200
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS
    expected_body: str | None = None
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "HealthCheckConfig":
        check_id = _coerce_str(raw["id"], "id")
        url = _coerce_str(raw["url"], "url")

        method = str(raw.get("method") or raw.get("httpMethod") or raw.get("http_method") or "GET").strip().upper()
        if method not in HTTP_METHODS:
            raise ValueError(f"method '{method}' is not supported")

        expected_status = _coerce_strict_status(
            raw.get("expectedStatus", raw.get("expected_status", 200))
        )
        interval_seconds = _coerce_optional_int(
            raw.get("intervalSeconds", raw.get("interval_seconds")),
            "intervalSeconds",
            DEFAULT_INTERVAL_SECONDS,
        )
        timeout_seconds = _coerce_optional_int(
            raw.get("timeoutSeconds", raw.get("timeout_seconds")),
            "timeoutSeconds",
            DEFAULT_TIMEOUT_SECONDS,
        )

        return cls(
            id=check_id,
            url=url,
            http_method=method,
            expected_status=expected_status,
            interval_seconds=interval_seconds,
            expected_body=_coerce_optional_str(raw.get("expectedBody", raw.get("expected_body"))),
            timeout_seconds=timeout_seconds,
        )
