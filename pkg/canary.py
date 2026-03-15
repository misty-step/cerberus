"""Canary observability sinks for health checks and error tracking."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Optional
from urllib import request

from .errortracking.grouper import ErrorAlert
from .healthcheck.checker import HealthTransition

HttpPost = Callable[[str, dict[str, str], bytes], None]


def _default_post(url: str, headers: dict[str, str], data: bytes) -> None:
    req = request.Request(url, data=data, method="POST", headers=headers)
    with request.urlopen(req, timeout=10):
        pass


def _post(endpoint: str, api_key: str, payload: dict[str, Any], poster: HttpPost) -> None:
    url = f"{endpoint.rstrip('/')}/api/v1/errors"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    poster(url, headers, data)


@dataclass(frozen=True)
class CanaryHealthSink:
    """Translates HealthTransition events to Canary error ingest."""

    endpoint: str
    api_key: str
    service: str = "cerberus"
    http_post: Optional[HttpPost] = None

    def send(self, transition: HealthTransition) -> None:
        payload = {
            "service": self.service,
            "error_class": f"HealthCheck:{transition.id}",
            "message": f"{transition.id}: {transition.previous_status} -> {transition.current_status}",
            "severity": "error" if transition.current_status == "unhealthy" else "info",
            "context": {
                "check_id": transition.id,
                "status_code": transition.result.status_code,
                "response_time_ms": transition.result.response_time_ms,
                "error": transition.result.error,
            },
        }
        try:
            _post(self.endpoint, self.api_key, payload, self.http_post or _default_post)
        except Exception:
            return


@dataclass(frozen=True)
class CanaryErrorSink:
    """Translates ErrorAlert events to Canary error ingest."""

    endpoint: str
    api_key: str
    service: str = "cerberus"
    http_post: Optional[HttpPost] = None

    def send(self, alert: ErrorAlert) -> None:
        payload = {
            "service": self.service,
            "error_class": f"ErrorTracking:{alert.error_key}",
            "message": alert.message,
            "severity": "warning",
            "context": {
                "alert_code": alert.code,
                "count": alert.count,
                "current_window_count": alert.current_window_count,
                "previous_window_count": alert.previous_window_count,
                "source_ids": alert.source_ids,
            },
        }
        try:
            _post(self.endpoint, self.api_key, payload, self.http_post or _default_post)
        except Exception:
            return
