from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from urllib.parse import urlparse
from typing import Any


HTTP_METHODS = {"GET", "POST"}
DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_TIMEOUT_SECONDS = 10
URL_SCHEMES = {"http", "https"}
BLOCKED_HOSTS = {
    "localhost",
    "metadata.google.internal",
    "metadata",
    "169.254.169.254",
    "100.100.100.200",
    "100.100.100.201",
}
BLOCKED_CIDRS = (ipaddress.ip_network("100.64.0.0/10"),)


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


def _is_blocked_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or any(ip in network for network in BLOCKED_CIDRS)
    )


def _validate_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in URL_SCHEMES:
        raise ValueError("url scheme must be http or https")

    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError("url must include a hostname")
    if host in BLOCKED_HOSTS:
        raise ValueError(f"url host '{host}' is blocked")
    if _is_blocked_ip(host):
        raise ValueError(f"url host '{host}' is blocked")

    return url


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
        """From dict."""
        check_id = _coerce_str(raw["id"], "id")
        url = _validate_url(_coerce_str(raw["url"], "url"))

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
