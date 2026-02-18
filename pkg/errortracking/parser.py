"""Log parsing for agentic error tracking."""

from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .config import ErrorSourceConfig


@dataclass(frozen=True)
class ParsedError:
    """A single detected error event extracted from a log source."""

    error_key: str
    signature: str
    message: str
    source_id: str
    seen_at: float
    seen_at_iso: str
    matched_pattern: str
    stack_trace: str | None = None
    raw_record: str | dict[str, object] | None = None


def _normalize_signature(text: str) -> str:
    normalized = " ".join((text or "").split()).lower()
    normalized = re.sub(r"\b0x[0-9a-f]+\b", "0x<id>", normalized)
    normalized = re.sub(r"\b[0-9a-f]{8,}\b", "<id>", normalized)
    normalized = re.sub(r"\b\d+\b", "<num>", normalized)
    return normalized.strip() or "error"


def _parse_datetime(value: Any, now_ts: float) -> tuple[float, str]:
    if value is None:
        dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)
        return now_ts, dt.isoformat()
    if isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
        return dt.timestamp(), dt.isoformat()
    if not isinstance(value, str):
        dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)
        return now_ts, dt.isoformat()

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)
        return dt.timestamp(), dt.isoformat()

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.timestamp(), dt.isoformat()


def _read_lines(config: ErrorSourceConfig) -> list[str]:
    try:
        with open(config.log_file, "r", encoding="utf-8", errors="replace") as stream:
            if config.poll_lines is None:
                return stream.read().splitlines()
            return list(deque(stream, maxlen=config.poll_lines))
    except FileNotFoundError:
        return []


class LogParser:
    """Parses log files into typed `ParsedError` events."""

    def __init__(self, source: ErrorSourceConfig) -> None:
        self._source = source
        self._pattern_regex = tuple(re.compile(pattern, re.IGNORECASE) for pattern in source.error_patterns)

    def _build_signature(self, message: str, stack_trace: str | None) -> str:
        if stack_trace:
            return _normalize_signature(stack_trace)
        return _normalize_signature(message)

    def _parse_timestamp(self, raw: Any, fallback_ts: float) -> tuple[float, str]:
        return _parse_datetime(raw, fallback_ts)

    def _match(self, text: str) -> str | None:
        for regex in self._pattern_regex:
            if regex.search(text):
                return regex.pattern
        return None

    def _parse_plain_line(self, line: str, now_ts: float) -> ParsedError | None:
        matched = self._match(line)
        if matched is None:
            return None

        seen_ts, seen_iso = self._parse_timestamp(None, now_ts)
        signature = self._build_signature(line, stack_trace=None)
        return ParsedError(
            error_key=f"{self._source.source_id}:{signature}",
            signature=signature,
            message=line.strip(),
            source_id=self._source.source_id,
            seen_at=seen_ts,
            seen_at_iso=seen_iso,
            matched_pattern=matched,
            raw_record=line,
        )

    def _parse_json_line(self, line: str, now_ts: float) -> ParsedError | None:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(record, dict):
            return None

        message = record.get(self._source.message_field) or record.get("message") or ""
        message = str(message)
        stack_trace = record.get(self._source.stack_field)
        if not isinstance(stack_trace, str):
            stack_trace = None

        searchable = message
        if stack_trace:
            searchable = f"{searchable} {stack_trace}"
        matched = self._match(searchable)
        if matched is None:
            return None

        raw_ts = record.get(self._source.timestamp_field) if self._source.timestamp_field else None
        seen_ts, seen_iso = self._parse_timestamp(raw_ts, now_ts)
        signature = self._build_signature(message, stack_trace=stack_trace)
        return ParsedError(
            error_key=f"{self._source.source_id}:{signature}",
            signature=signature,
            message=message,
            source_id=self._source.source_id,
            seen_at=seen_ts,
            seen_at_iso=seen_iso,
            matched_pattern=matched,
            stack_trace=stack_trace,
            raw_record=record,
        )

    def parse(self) -> list[ParsedError]:
        parser = self._parse_plain_line if self._source.log_format == "plain" else self._parse_json_line
        now_ts = datetime.now(tz=timezone.utc).timestamp()
        parsed: list[ParsedError] = []

        for line in _read_lines(self._source):
            parsed_error = parser(line, now_ts)
            if parsed_error is not None:
                parsed.append(parsed_error)
        return parsed
