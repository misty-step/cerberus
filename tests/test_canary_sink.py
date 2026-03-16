"""Tests for Canary observability sink (pkg.canary)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from pkg.canary import CanaryErrorSink, CanaryHealthSink
from pkg.errortracking.grouper import ErrorAlert
from pkg.healthcheck.checker import HealthCheckResult, HealthTransition, HEALTHY, UNHEALTHY


def _health_transition(
    check_id: str = "api",
    previous: str = HEALTHY,
    current: str = UNHEALTHY,
    status_code: int = 500,
    error: str | None = "connection refused",
) -> HealthTransition:
    result = HealthCheckResult(
        id=check_id,
        status=current,
        status_code=status_code,
        response_time_ms=42,
        timestamp="2026-03-15T12:00:00+00:00",
        error=error,
    )
    return HealthTransition(id=check_id, previous_status=previous, current_status=current, result=result)


def _error_alert(
    code: str = "new_error_type",
    error_key: str = "api:database connection failure",
    message: str = "DatabaseError: connection refused",
) -> ErrorAlert:
    return ErrorAlert(
        code=code,
        error_key=error_key,
        message=message,
        count=5,
        current_window_count=4,
        previous_window_count=1,
        source_ids=["api", "worker"],
        timestamp="2026-03-15T12:00:00+00:00",
    )


# --- CanaryHealthSink ---


def test_health_sink_sends_correct_payload():
    payloads: list[tuple[str, dict[str, str], bytes]] = []

    def recorder(url: str, headers: dict[str, str], data: bytes) -> None:
        payloads.append((url, headers, data))

    sink = CanaryHealthSink(
        endpoint="https://canary-obs.fly.dev",
        api_key="test-key",
        http_post=recorder,
    )
    sink.send(_health_transition())

    assert len(payloads) == 1
    url, headers, raw = payloads[0]
    assert url == "https://canary-obs.fly.dev/api/v1/errors"
    assert headers["Authorization"] == "Bearer test-key"
    assert headers["Content-Type"] == "application/json"

    body = json.loads(raw)
    assert body["service"] == "cerberus"
    assert body["error_class"] == "HealthCheck:api"
    assert "healthy" in body["message"].lower() and "unhealthy" in body["message"].lower()
    assert body["severity"] == "error"


def test_health_sink_recovery_sends_info_severity():
    payloads: list[bytes] = []

    sink = CanaryHealthSink(
        endpoint="https://canary-obs.fly.dev",
        api_key="k",
        http_post=lambda _u, _h, d: payloads.append(d),
    )
    sink.send(_health_transition(previous=UNHEALTHY, current=HEALTHY, status_code=200, error=None))

    body = json.loads(payloads[0])
    assert body["severity"] == "info"


def test_health_sink_includes_context():
    payloads: list[bytes] = []

    sink = CanaryHealthSink(
        endpoint="https://x",
        api_key="k",
        http_post=lambda _u, _h, d: payloads.append(d),
    )
    sink.send(_health_transition())

    ctx = json.loads(payloads[0])["context"]
    assert ctx["check_id"] == "api"
    assert ctx["status_code"] == 500
    assert ctx["response_time_ms"] == 42


def test_health_sink_custom_service():
    payloads: list[bytes] = []

    sink = CanaryHealthSink(
        endpoint="https://x",
        api_key="k",
        service="my-service",
        http_post=lambda _u, _h, d: payloads.append(d),
    )
    sink.send(_health_transition())

    assert json.loads(payloads[0])["service"] == "my-service"


def test_health_sink_swallows_post_errors():
    def explode(_u: str, _h: dict, _d: bytes) -> None:
        raise ConnectionError("network down")

    sink = CanaryHealthSink(endpoint="https://x", api_key="k", http_post=explode)
    sink.send(_health_transition())  # must not raise


# --- CanaryErrorSink ---


def test_error_sink_sends_correct_payload():
    payloads: list[tuple[str, dict[str, str], bytes]] = []

    def recorder(url: str, headers: dict[str, str], data: bytes) -> None:
        payloads.append((url, headers, data))

    sink = CanaryErrorSink(
        endpoint="https://canary-obs.fly.dev",
        api_key="test-key",
        http_post=recorder,
    )
    sink.send(_error_alert())

    assert len(payloads) == 1
    url, headers, raw = payloads[0]
    assert url == "https://canary-obs.fly.dev/api/v1/errors"
    assert headers["Authorization"] == "Bearer test-key"

    body = json.loads(raw)
    assert body["service"] == "cerberus"
    assert body["error_class"] == "ErrorTracking:api:database connection failure"
    assert body["message"] == "DatabaseError: connection refused"
    assert body["severity"] == "warning"


def test_error_sink_spike_sends_warning():
    payloads: list[bytes] = []

    sink = CanaryErrorSink(
        endpoint="https://x",
        api_key="k",
        http_post=lambda _u, _h, d: payloads.append(d),
    )
    sink.send(_error_alert(code="error_rate_spike"))

    assert json.loads(payloads[0])["severity"] == "warning"


def test_error_sink_includes_context():
    payloads: list[bytes] = []

    sink = CanaryErrorSink(
        endpoint="https://x",
        api_key="k",
        http_post=lambda _u, _h, d: payloads.append(d),
    )
    sink.send(_error_alert())

    ctx = json.loads(payloads[0])["context"]
    assert ctx["alert_code"] == "new_error_type"
    assert ctx["count"] == 5
    assert ctx["source_ids"] == ["api", "worker"]


def test_error_sink_swallows_post_errors():
    def explode(_u: str, _h: dict, _d: bytes) -> None:
        raise ConnectionError("network down")

    sink = CanaryErrorSink(endpoint="https://x", api_key="k", http_post=explode)
    sink.send(_error_alert())  # must not raise
