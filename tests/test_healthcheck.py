from __future__ import annotations

import io
import pytest
from urllib import error

from pkg.healthcheck import (
    GitHubIssueAlertSink,
    HealthCheckConfig,
    HealthCheckResult,
    HealthMonitor,
    HealthChecker,
    HEALTHY,
    PRCommentAlertSink,
    UNHEALTHY,
    WebhookAlertSink,
)
from pkg.healthcheck.checker import HealthTransition


def test_config_from_dict_supports_defaults():
    cfg = HealthCheckConfig.from_dict({"id": "api", "url": "https://example.test"})
    assert cfg.id == "api"
    assert cfg.http_method == "GET"
    assert cfg.interval_seconds == 300
    assert cfg.expected_status == 200


def test_config_from_dict_validates_values():
    cfg = HealthCheckConfig.from_dict(
        {
            "id": "search",
            "url": "https://example.test/health",
            "method": "POST",
            "expectedStatus": 204,
            "intervalSeconds": 120,
            "expectedBody": "ok",
            "timeoutSeconds": 4,
        }
    )
    assert cfg.id == "search"
    assert cfg.http_method == "POST"
    assert cfg.expected_status == 204
    assert cfg.interval_seconds == 120
    assert cfg.expected_body == "ok"
    assert cfg.timeout_seconds == 4


def test_config_from_dict_invalid_status_raises():
    with pytest.raises(ValueError, match="expectedStatus"):
        HealthCheckConfig.from_dict({"id": "bad", "url": "https://x", "expectedStatus": 99})


def test_config_from_dict_blocks_localhost():
    with pytest.raises(ValueError, match="blocked"):
        HealthCheckConfig.from_dict({"id": "bad", "url": "http://localhost/health"})


def test_config_from_dict_blocks_private_ip():
    with pytest.raises(ValueError, match="blocked"):
        HealthCheckConfig.from_dict({"id": "bad", "url": "http://192.168.1.10/health"})


class _ContextResponse:
    def __init__(self, status: int, body: str = ""):
        self.status = status
        self._body = body.encode()

    def read(self, _size: int = -1) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def test_healthchecker_reports_healthy_on_expected_status_and_body():
    cfg = HealthCheckConfig.from_dict(
        {"id": "api", "url": "https://example.test", "expectedStatus": 200, "expectedBody": "ok"}
    )
    checker = HealthChecker(opener=lambda _req, _timeout: _ContextResponse(200, "all ok"))
    result = checker.perform_check(cfg)
    assert result.status == HEALTHY
    assert result.status_code == 200
    assert result.error is None


def test_healthchecker_marks_unhealthy_on_status_mismatch():
    cfg = HealthCheckConfig.from_dict({"id": "api", "url": "https://example.test", "expectedStatus": 200})
    checker = HealthChecker(opener=lambda _req, _timeout: _ContextResponse(500, "oops"))
    result = checker.perform_check(cfg)
    assert result.status == UNHEALTHY
    assert result.status_code == 500
    assert "expected status 200, got 500" in result.error


def test_healthchecker_marks_unhealthy_on_body_mismatch():
    cfg = HealthCheckConfig.from_dict(
        {"id": "api", "url": "https://example.test", "expectedStatus": 200, "expectedBody": "green"}
    )
    checker = HealthChecker(opener=lambda _req, _timeout: _ContextResponse(200, "all red"))
    result = checker.perform_check(cfg)
    assert result.status == UNHEALTHY
    assert "expected text" in result.error


def test_healthchecker_marks_timeout_as_unhealthy():
    cfg = HealthCheckConfig.from_dict({"id": "api", "url": "https://example.test", "expectedStatus": 200})
    checker = HealthChecker(
        opener=lambda _req, _timeout: (_ for _ in ()).throw(error.URLError("timed out"))
    )
    result = checker.perform_check(cfg)
    assert result.status == UNHEALTHY
    assert result.error is not None


def test_healthchecker_handles_http_error_status_code():
    cfg = HealthCheckConfig.from_dict({"id": "api", "url": "https://example.test", "expectedStatus": 200})
    http_error = error.HTTPError(
        url=cfg.url,
        code=503,
        msg="service unavailable",
        hdrs=None,
        fp=io.BytesIO(b"unavailable"),
    )
    checker = HealthChecker(
        opener=lambda _req, _timeout: (_ for _ in ()).throw(http_error)
    )
    result = checker.perform_check(cfg)
    assert result.status == UNHEALTHY
    assert result.status_code == 503
    assert "expected status 200, got 503" in (result.error or "")


def test_healthchecker_allows_expected_http_error_status_code():
    cfg = HealthCheckConfig.from_dict({"id": "api", "url": "https://example.test", "expectedStatus": 503})
    http_error = error.HTTPError(
        url=cfg.url,
        code=503,
        msg="service unavailable",
        hdrs=None,
        fp=io.BytesIO(b"maintenance"),
    )
    checker = HealthChecker(
        opener=lambda _req, _timeout: (_ for _ in ()).throw(http_error)
    )
    result = checker.perform_check(cfg)
    assert result.status == HEALTHY
    assert result.status_code == 503
    assert result.error is None


def test_healthchecker_marks_generic_exception_as_unhealthy():
    cfg = HealthCheckConfig.from_dict({"id": "api", "url": "https://example.test", "expectedStatus": 200})
    checker = HealthChecker(
        opener=lambda _req, _timeout: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    result = checker.perform_check(cfg)
    assert result.status == UNHEALTHY
    assert "boom" in (result.error or "")


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[HealthTransition] = []

    def send(self, transition: HealthTransition) -> None:
        self.events.append(transition)


def test_health_monitor_alerts_only_on_state_transitions():
    cfg = HealthCheckConfig.from_dict({"id": "api", "url": "https://example.test", "expectedStatus": 200})
    outcomes = [HealthCheckResult("api", HEALTHY, 200, 1, "now"), HealthCheckResult("api", HEALTHY, 200, 1, "later"), HealthCheckResult("api", UNHEALTHY, 500, 1, "later"), HealthCheckResult("api", UNHEALTHY, 500, 1, "later"), HealthCheckResult("api", HEALTHY, 200, 1, "later")]

    def fake_opener(_req, _timeout):
        item = outcomes.pop(0)
        return _ContextResponse(item.status_code or 200, item.error or "")

    checker = HealthChecker(opener=fake_opener)
    sink = _RecordingSink()
    monitor = HealthMonitor(checker=checker, sinks=(sink,))
    results = []
    for _ in range(5):
        run_results, _alerts = monitor.run_checks([cfg])
        results.extend(run_results)

    assert len(results) == 5
    assert len(sink.events) == 2
    assert sink.events[0].previous_status == HEALTHY
    assert sink.events[0].current_status == UNHEALTHY
    assert sink.events[1].previous_status == UNHEALTHY
    assert sink.events[1].current_status == HEALTHY


def _transition() -> HealthTransition:
    result = HealthCheckResult(
        id="api",
        status=UNHEALTHY,
        status_code=500,
        response_time_ms=15,
        timestamp="2026-02-18T15:00:00+00:00",
        error="failure",
    )
    return HealthTransition(
        id="api",
        previous_status=HEALTHY,
        current_status=UNHEALTHY,
        result=result,
    )


def test_webhook_alert_sink_writes_payload():
    seen: list[dict[str, object]] = []

    def writer(payload: dict[str, object]) -> None:
        seen.append(payload)

    sink = WebhookAlertSink(webhook_url="https://hooks.example.test", write_payload=writer)
    sink.send(_transition())
    assert len(seen) == 1
    assert seen[0]["check_id"] == "api"
    assert seen[0]["previous_status"] == HEALTHY
    assert seen[0]["current_status"] == UNHEALTHY


def test_webhook_alert_sink_swallows_writer_errors():
    sink = WebhookAlertSink(
        webhook_url="https://hooks.example.test",
        write_payload=lambda _payload: (_ for _ in ()).throw(RuntimeError("down")),
    )
    sink.send(_transition())


def test_pr_comment_alert_sink_posts_payload():
    seen: list[dict[str, object]] = []
    sink = PRCommentAlertSink(post_comment=lambda payload: seen.append(payload))
    sink.send(_transition())
    assert len(seen) == 1
    assert seen[0]["state"] == "healthy -> unhealthy"


def test_github_issue_alert_sink_posts_payload():
    seen: list[dict[str, object]] = []
    sink = GitHubIssueAlertSink(create_issue=lambda payload: seen.append(payload))
    sink.send(_transition())
    assert len(seen) == 1
    assert "HealthCheck" in str(seen[0]["title"])
