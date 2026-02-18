"""Grouping, aggregation, and alerting for parsed errors."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Protocol

from .parser import ParsedError

MAX_GROUP_TEXT_CHARS = 4096


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
    timestamps: list[float] = field(default_factory=list)
    first_seen_ts: float | None = field(default=None, repr=False)
    last_seen_ts: float = field(default=0.0, repr=False)
    _timestamps_sorted: bool = field(default=True, repr=False)
    is_spiking: bool = False

    def add(self, event: ParsedError) -> None:
        self.count += 1
        if self.first_seen_ts is None or event.seen_at < self.first_seen_ts:
            self.first_seen_ts = event.seen_at
            self.first_seen = event.seen_at_iso
        if event.seen_at >= self.last_seen_ts:
            self.last_seen_ts = event.seen_at
            self.last_seen = event.seen_at_iso
        if event.source_id not in self.source_ids:
            self.source_ids.append(event.source_id)
            self.source_ids.sort()
        if self.timestamps and event.seen_at < self.timestamps[-1]:
            self._timestamps_sorted = False
        self.timestamps.append(event.seen_at)
        if self.last_seen_ts == 0.0:
            self.last_seen_ts = event.seen_at

    def trim(self, cutoff_ts: float, max_timestamps: int) -> None:
        if not self.timestamps:
            return
        if not self._timestamps_sorted:
            self.timestamps.sort()
            self._timestamps_sorted = True
        cutoff_idx = bisect_left(self.timestamps, cutoff_ts)
        if cutoff_idx > 0:
            self.timestamps = self.timestamps[cutoff_idx:]
        overflow = len(self.timestamps) - max_timestamps
        if overflow > 0:
            self.timestamps = self.timestamps[overflow:]


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


def _build_window_counts(timestamps: list[float], now_ts: float, window_seconds: int) -> tuple[int, int]:
    if not timestamps:
        return 0, 0

    current_start = now_ts - window_seconds
    previous_start = now_ts - (window_seconds * 2)
    end_idx = bisect_right(timestamps, now_ts)
    current_start_idx = bisect_right(timestamps, current_start, 0, end_idx)
    previous_start_idx = bisect_right(timestamps, previous_start, 0, current_start_idx)
    current_count = end_idx - current_start_idx
    previous_count = current_start_idx - previous_start_idx
    return current_count, previous_count


@dataclass
class ErrorGrouper:
    """Groups similar errors and emits transition/rate alerts."""

    spike_window_seconds: int = 3600
    spike_multiplier: float = 2.5
    spike_min_count: int = 5
    trend_bucket_seconds: int = 300
    trend_buckets: int = 12
    max_group_timestamps: int = 10_000
    max_groups: int = 1_000
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
        if self.max_group_timestamps <= 0:
            raise ValueError("max_group_timestamps must be greater than zero")
        if self.max_groups <= 0:
            raise ValueError("max_groups must be greater than zero")

    def _window_bounds(self, now_ts: float) -> float:
        return now_ts - self._retention_seconds()

    def _retention_seconds(self) -> int:
        return max(self.spike_window_seconds * 2, self.trend_bucket_seconds * self.trend_buckets)

    def _is_rate_spike(self, current_count: int, previous_count: int) -> bool:
        if previous_count <= 0:
            return False
        threshold = max(
            int(self.spike_multiplier * previous_count),
            self.spike_min_count,
        )
        return current_count >= threshold

    def _build_trend(self, timestamps: list[float], now_ts: float) -> list[int]:
        bucket_start = now_ts - (self.trend_bucket_seconds * self.trend_buckets)
        buckets = [0 for _ in range(self.trend_buckets)]
        if not timestamps:
            return buckets

        start_idx = bisect_right(timestamps, bucket_start)
        end_idx = bisect_right(timestamps, now_ts, start_idx)
        for value in timestamps[start_idx:end_idx]:
            bucket = int((value - bucket_start) // self.trend_bucket_seconds)
            if bucket >= self.trend_buckets:
                bucket = self.trend_buckets - 1
            buckets[bucket] += 1
        return buckets

    def _evict_stale_groups(self, cutoff_ts: float) -> None:
        stale_keys = []
        for key, group in self._groups.items():
            if group.last_seen_ts < cutoff_ts:
                stale_keys.append(key)
        for key in stale_keys:
            self._groups.pop(key, None)

    def _evict_one_lru_group(self) -> None:
        if len(self._groups) < self.max_groups:
            return
        lru_key = min(self._groups, key=lambda key: self._groups[key].last_seen_ts)
        self._groups.pop(lru_key, None)

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
        latest_seen_ts: float | None = None
        self._sink_errors.clear()
        latest_event_by_group: dict[str, ParsedError] = {}
        new_group_keys: set[str] = set()

        for event in errors:
            group = self._groups.get(event.error_key)
            is_new_group = group is None
            if group is None:
                self._evict_one_lru_group()
                group = ErrorGroup(
                    error_key=event.error_key,
                    signature=event.signature[:MAX_GROUP_TEXT_CHARS],
                    message=event.message[:MAX_GROUP_TEXT_CHARS],
                )
                self._groups[event.error_key] = group
            now_ts = event.seen_at
            latest_seen_ts = now_ts if latest_seen_ts is None else max(latest_seen_ts, now_ts)
            group.add(event)
            existing = latest_event_by_group.get(event.error_key)
            if existing is None or event.seen_at >= existing.seen_at:
                latest_event_by_group[event.error_key] = event

            if is_new_group:
                new_group_keys.add(event.error_key)

        for error_key, latest_event in latest_event_by_group.items():
            group = self._groups[error_key]
            group.trim(self._window_bounds(latest_event.seen_at), self.max_group_timestamps)
            current_count, previous_count = _build_window_counts(
                group.timestamps, latest_event.seen_at, self.spike_window_seconds
            )

            if error_key in new_group_keys:
                alert = ErrorAlert(
                    code="new_error_type",
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

            if error_key in new_group_keys and group.count == 1:
                continue

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

        if latest_seen_ts is not None:
            self._evict_stale_groups(latest_seen_ts - self._retention_seconds())

        return list(self._groups.values()), alerts

    def build_dashboard(self, as_of_ts: float | None = None) -> dict[str, object]:
        now_ts = datetime.now(tz=timezone.utc).timestamp() if as_of_ts is None else as_of_ts
        now_iso = datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat()
        self._evict_stale_groups(now_ts - self._retention_seconds())

        errors = []
        for group in sorted(self._groups.values(), key=lambda item: item.count, reverse=True):
            group.trim(self._window_bounds(now_ts), self.max_group_timestamps)
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
