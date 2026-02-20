from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable, Sequence
from urllib import error
from urllib import request

from .config import HealthCheckConfig


HealthHttpOpen = Callable[[request.Request, int], object]
HealthStatus = str

HEALTHY = "healthy"
UNHEALTHY = "unhealthy"


@dataclass(frozen=True)
class HealthCheckResult:
    """Data class for Health Check Result."""
    id: str
    status: HealthStatus
    status_code: int | None
    response_time_ms: int
    timestamp: str
    error: str | None = None


@dataclass(frozen=True)
class HealthTransition:
    """Data class for Health Transition."""
    id: str
    previous_status: HealthStatus
    current_status: HealthStatus
    result: HealthCheckResult


@dataclass
class HealthChecker:
    """Data class for Health Checker."""
    opener: HealthHttpOpen | None = None

    def __post_init__(self) -> None:
        if self.opener is None:
            self.opener = _default_opener

    def _build_response(self, health_id: str, status: HealthStatus, status_code: int | None, started: float, error: str | None = None) -> HealthCheckResult:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return HealthCheckResult(
            id=health_id,
            status=status,
            status_code=status_code,
            response_time_ms=elapsed_ms,
            timestamp=datetime.now(timezone.utc).isoformat(),
            error=error,
        )

    def _check_expected_body(self, body: str, expected_body: str | None) -> str | None:
        if expected_body is None:
            return None
        if expected_body in body:
            return None
        return f"response body does not contain expected text: {expected_body}"

    def _read_body(self, response: object) -> str:
        read = getattr(response, "read")
        if read is None:
            return ""
        raw = read(2048)
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        if isinstance(raw, str):
            return raw
        return ""

    def _evaluate_response(self, config: HealthCheckConfig, status_code: int, body: str, started: float) -> HealthCheckResult:
        if status_code != config.expected_status:
            return self._build_response(
                config.id,
                UNHEALTHY,
                status_code,
                started,
                f"expected status {config.expected_status}, got {status_code}",
            )

        body_error = self._check_expected_body(body, config.expected_body)
        if body_error is not None:
            return self._build_response(
                config.id,
                UNHEALTHY,
                status_code,
                started,
                body_error,
            )

        return self._build_response(config.id, HEALTHY, status_code, started)

    def perform_check(self, config: HealthCheckConfig) -> HealthCheckResult:
        """Perform check."""
        started = time.perf_counter()
        req = request.Request(config.url, method=config.http_method)
        opener = self.opener
        if opener is None:
            opener = _default_opener

        try:
            with opener(req, config.timeout_seconds) as response:
                status_code = int(getattr(response, "status", 0))
                body = self._read_body(response)
                return self._evaluate_response(config, status_code, body, started)

        except error.HTTPError as exc:
            # urllib turns non-2xx responses into exceptions, but those still carry a status code + body.
            status_code = int(getattr(exc, "code", 0))
            body = self._read_body(exc)
            return self._evaluate_response(config, status_code, body, started)

        except error.URLError as exc:
            return self._build_response(
                config.id,
                UNHEALTHY,
                None,
                started,
                str(exc.reason) if hasattr(exc, "reason") else str(exc),
            )
        except Exception as exc:
            return self._build_response(config.id, UNHEALTHY, None, started, str(exc))


class HealthMonitor:
    """Data class for Health Monitor."""
    def __init__(self, checker: HealthChecker | None = None, sinks: Sequence["object"] | None = None) -> None:
        self._checker = checker or HealthChecker()
        self._sinks = tuple(sinks or ())
        self._previous_statuses: dict[str, HealthStatus] = {}

    def _should_alert(self, previous_status: HealthStatus | None, current_status: HealthStatus) -> bool:
        if previous_status not in {HEALTHY, UNHEALTHY}:
            return False
        return previous_status != current_status

    def run_checks(self, checks: Iterable[HealthCheckConfig]) -> tuple[list[HealthCheckResult], list[HealthTransition]]:
        """Run checks."""
        results = []
        alerts = []
        for cfg in checks:
            result = self._checker.perform_check(cfg)
            results.append(result)

            previous_status = self._previous_statuses.get(cfg.id)
            if self._should_alert(previous_status, result.status):
                transition = HealthTransition(cfg.id, previous_status or HEALTHY, result.status, result)
                for sink in self._sinks:
                    send = getattr(sink, "send", None)
                    if callable(send):
                        try:
                            send(transition)
                        except Exception:
                            # Alert sinks are best-effort: never block checks.
                            pass
                alerts.append(transition)

            self._previous_statuses[cfg.id] = result.status

        return results, alerts


def _default_opener(req: request.Request, timeout_seconds: int) -> object:
    return request.urlopen(req, timeout=timeout_seconds)
