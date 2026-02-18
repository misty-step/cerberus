"""Grouping, aggregation, and alerting for parsed errors."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Protocol

from .parser import ParsedError


class ErrorAlertSink(Protocol):
    def send(self, alert: "ErrorAlert") -> None:
        ...


@dataclass
class ErrorGroup:
    """Aggregated counters and trend data for one error fingerprint."""

    error_key: str
    signature: str
    message: str
    count: int = 0
    first_seen: str = ""
    last_seen: str = ""
    source_ids: list[str] = field(default_factory=list)
    timestamps: deque[float] = field(default_factory=deque)
    is_spiking: bool = False

    def add(self, event: ParsedError) -> None:
        self.count += 1
        self.last_seen = event.seen_at_iso
        if not self.first_seen:
            self.first_seen = event.seen_at_iso
        if event.source_id not in self.source_ids:
            self.source_ids.append(event.source_id)
            self.source_ids.sort()
        self.timestamps.append(event.seen_at)

    def trim(self, cutoff_ts: float) -> None:
        while self.timestamps and self.timestamps[0] < cutoff_ts:
            self.timestamps.popleft()


@dataclass(frozen=True)
class ErrorAlert:
    """Best-effort alert describing a new condition in error behavior."""

    code: str
    error_key: str
    message: str
    count: int
    current_window_count: int
    previous_window_count: int
    source_ids: list[str]
    timestamp: str


def _build_window_counts(timestamps: deque[float], now_ts: float, window_seconds: int) -> tuple[int, int]:
    current_start = now_ts - window_seconds
    previous_start = now_ts - (window_seconds * 2)

    current_count = 0
    previous_count = 0
    for value in timestamps:
        if previous_start < value <= now_ts:
            if value <= current_start:
                previous_count += 1
            else:
                current_count += 1
    return current_count, previous_count


@dataclass
class ErrorGrouper:
    """Groups similar errors and emits transition/rate alerts."""

    spike_window_seconds: int = 3600
    spike_multiplier: float = 2.5
    spike_min_count: int = 5
    trend_bucket_seconds: int = 300
    trend_buckets: int = 12
    _groups: dict[str, ErrorGroup] = field(default_factory=dict, init=False, repr=False)
    _sink_errors: list[str] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.spike_window_seconds <= 0:
            raise ValueError("spike_window_seconds must be greater than zero")
        if self.spike_multiplier <= 0:
            raise ValueError("spike_multiplier must be greater than zero")
        if self.spike_min_count <= 0:
            raise ValueError("spike_min_count must be greater than zero")
        if self.trend_bucket_seconds <= 0:
            raise ValueError("trend_bucket_seconds must be greater than zero")
        if self.trend_buckets <= 0:
            raise ValueError("trend_buckets must be greater than zero")

    def _window_bounds(self, now_ts: float) -> float:
        retention = max(self.spike_window_seconds * 2, self.trend_bucket_seconds * self.trend_buckets)
        return now_ts - retention

    def _is_rate_spike(self, current_count: int, previous_count: int) -> bool:
        if previous_count <= 0:
            return False
        threshold = max(
            int(self.spike_multiplier * previous_count),
            self.spike_min_count,
        )
        return current_count >= threshold

    def _build_trend(self, timestamps: deque[float], now_ts: float) -> list[int]:
        bucket_start = now_ts - (self.trend_bucket_seconds * self.trend_buckets)
        buckets = [0 for _ in range(self.trend_buckets)]

        for value in timestamps:
            if value <= bucket_start or value > now_ts:
                continue
            bucket = int((value - bucket_start) // self.trend_bucket_seconds)
            if bucket >= self.trend_buckets:
                bucket = self.trend_buckets - 1
            buckets[bucket] += 1
        return buckets

    def _dispatch_alert(self, alert: ErrorAlert, sinks: list[ErrorAlertSink] | None) -> None:
        if not sinks:
            return
        for sink in sinks:
            try:
                sink.send(alert)
            except Exception as exc:
                self._sink_errors.append(f"{type(exc).__name__}: {exc}")

    def ingest(self, errors: Iterable[ParsedError], sinks: list[ErrorAlertSink] | None = None) -> tuple[list[ErrorGroup], list[ErrorAlert]]:
        alerts: list[ErrorAlert] = []
        self._sink_errors.clear()
        latest_event_by_group: dict[str, ParsedError] = {}
        new_group_keys: set[str] = set()

        for event in errors:
            group = self._groups.setdefault(
                event.error_key,
                ErrorGroup(
                    error_key=event.error_key,
                    signature=event.signature,
                    message=event.message,
                ),
            )

            is_new_group = group.count == 0
            now_ts = event.seen_at
            group.add(event)
            latest_event_by_group[event.error_key] = event

            cutoff = self._window_bounds(now_ts)
            group.trim(cutoff)

            if is_new_group:
                new_group_keys.add(event.error_key)
                current_count, previous_count = _build_window_counts(
                    group.timestamps, now_ts, self.spike_window_seconds
                )
                alert = ErrorAlert(
                    code="new_error_type",
                    error_key=event.error_key,
                    message=event.message,
                    count=group.count,
                    current_window_count=current_count,
                    previous_window_count=previous_count,
                    source_ids=list(group.source_ids),
                    timestamp=event.seen_at_iso,
                )
                alerts.append(alert)
                self._dispatch_alert(alert, sinks)

        for error_key, latest_event in latest_event_by_group.items():
            if error_key in new_group_keys and self._groups[error_key].count == 1:
                continue

            group = self._groups[error_key]
            current_count, previous_count = _build_window_counts(
                group.timestamps, latest_event.seen_at, self.spike_window_seconds
            )
            is_spike = self._is_rate_spike(current_count, previous_count)
            if not group.is_spiking and is_spike:
                alert = ErrorAlert(
                    code="error_rate_spike",
                    error_key=group.error_key,
                    message=group.message,
                    count=group.count,
                    current_window_count=current_count,
                    previous_window_count=previous_count,
                    source_ids=list(group.source_ids),
                    timestamp=latest_event.seen_at_iso,
                )
                alerts.append(alert)
                self._dispatch_alert(alert, sinks)
            group.is_spiking = is_spike

        return list(self._groups.values()), alerts

    def build_dashboard(self, as_of_ts: float | None = None) -> dict[str, object]:
        now_ts = datetime.now(tz=timezone.utc).timestamp() if as_of_ts is None else as_of_ts
        now_iso = datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat()

        errors = []
        for group in sorted(self._groups.values(), key=lambda item: item.count, reverse=True):
            current_count, previous_count = _build_window_counts(group.timestamps, now_ts, self.spike_window_seconds)
            errors.append(
                {
                    "error_key": group.error_key,
                    "signature": group.signature,
                    "message": group.message,
                    "count": group.count,
                    "first_seen": group.first_seen,
                    "last_seen": group.last_seen,
                    "sources": list(group.source_ids),
                    "trend": {
                        "current_window_count": current_count,
                        "previous_window_count": previous_count,
                        "buckets": self._build_trend(group.timestamps, now_ts),
                        "bucket_seconds": self.trend_bucket_seconds,
                    },
                }
            )

        return {
            "generated_at": now_iso,
            "spike_window_seconds": self.spike_window_seconds,
            "errors": errors,
        }

    @property
    def groups(self) -> dict[str, ErrorGroup]:
        return dict(self._groups)

    @property
    def sink_errors(self) -> list[str]:
        return list(self._sink_errors)
