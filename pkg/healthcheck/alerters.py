from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Optional, Protocol
from urllib import request

from .checker import HealthTransition


class AlertSink(Protocol):
    def send(self, transition: HealthTransition) -> None:
        ...


PayloadWriter = Callable[[dict[str, object]], None]


def _default_webhook_writer(payload: dict[str, object], webhook_url: str) -> None:
    data = json.dumps(payload).encode()
    req = request.Request(
        webhook_url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with request.urlopen(req, timeout=10):
        pass


@dataclass(frozen=True)
class WebhookAlertSink:
    webhook_url: str
    write_payload: Optional[PayloadWriter] = None

    def send(self, transition: HealthTransition) -> None:
        payload = {
            "check_id": transition.id,
            "previous_status": transition.previous_status,
            "current_status": transition.current_status,
            "status_code": transition.result.status_code,
            "response_time_ms": transition.result.response_time_ms,
            "timestamp": transition.result.timestamp,
            "error": transition.result.error,
        }
        writer = self.write_payload or (lambda data: _default_webhook_writer(data, self.webhook_url))
        try:
            writer(payload)
        except Exception:
            # Best-effort: webhook failures should not crash the caller.
            return


@dataclass(frozen=True)
class PRCommentAlertSink:
    post_comment: Optional[PayloadWriter] = None

    def send(self, transition: HealthTransition) -> None:
        payload = {
            "check_id": transition.id,
            "state": f"{transition.previous_status} -> {transition.current_status}",
            "status_code": transition.result.status_code,
            "error": transition.result.error or "",
            "timestamp": transition.result.timestamp,
        }
        if self.post_comment is not None:
            self.post_comment(payload)


@dataclass(frozen=True)
class GitHubIssueAlertSink:
    create_issue: Optional[PayloadWriter] = None

    def send(self, transition: HealthTransition) -> None:
        if self.create_issue is None:
            return
        payload = {
            "title": f"[HealthCheck] {transition.id}: {transition.current_status}",
            "body": (
                f"- check: {transition.id}\n"
                f"- state: {transition.previous_status} -> {transition.current_status}\n"
                f"- status_code: {transition.result.status_code}\n"
                f"- error: {transition.result.error or 'none'}\n"
                f"- timestamp: {transition.result.timestamp}\n"
            ),
        }
        self.create_issue(payload)
