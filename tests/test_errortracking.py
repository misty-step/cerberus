from __future__ import annotations

from pathlib import Path

from pkg.errortracking.config import ErrorSourceConfig
from pkg.errortracking.grouper import ErrorGrouper
from pkg.errortracking.parser import LogParser, ParsedError


def _make_error(source: str, signature: str, ts: float, message: str = "Database error") -> ParsedError:
    return ParsedError(
        error_key=f"{source}:{signature}",
        signature=signature,
        message=message,
        source_id=source,
        seen_at=ts,
        seen_at_iso=f"2026-02-17T{int(ts)}Z",
        matched_pattern="Database",
        raw_record=None,
    )


def test_log_parser_detects_plain_patterns(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    log.write_text(
        "\n".join(
            [
                "INFO startup",
                "ERROR DatabaseError: connection refused",
                "WARN retrying",
                "CRITICAL panic in worker",
            ]
        )
    )

    parser = LogParser(
        ErrorSourceConfig.from_dict(
            {
                "id": "api",
                "path": str(log),
                "format": "plain",
                "errorPatterns": ["ERROR", "CRITICAL"],
            }
        )
    )
    parsed = parser.parse()

    assert len(parsed) == 2
    assert parsed[0].source_id == "api"
    assert parsed[0].signature != parsed[1].signature


def test_log_parser_detects_json_errors_and_extracts_stack(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    log.write_text(
        "\n".join(
            [
                '{"message":"DatabaseError: connection refused","stack":"Traceback 1"}',
                '{"message":"debug info"}',
                '{"message":"DatabaseError: timeout","stack":"Traceback 1"}',
            ]
        )
    )
    parser = LogParser(
        ErrorSourceConfig.from_dict(
            {
                "id": "worker",
                "path": str(log),
                "format": "json",
                "messageField": "message",
                "stackField": "stack",
                "errorPatterns": ["DatabaseError"],
            }
        )
    )

    parsed = parser.parse()
    assert len(parsed) == 2
    assert parsed[0].stack_trace == "Traceback 1"
    assert parsed[0].signature == parsed[1].signature


def test_error_grouper_creates_new_error_alert_once() -> None:
    grouper = ErrorGrouper(spike_window_seconds=300, spike_multiplier=1.5, spike_min_count=4, trend_bucket_seconds=60, trend_buckets=4)
    events = [
        _make_error("api", "database connection failure", 1690000350.0),
        _make_error("api", "database connection failure", 1690000400.0),
        _make_error("api", "database connection failure", 1690000650.0),
        _make_error("api", "database connection failure", 1690000680.0),
        _make_error("api", "database connection failure", 1690000710.0),
        _make_error("api", "database connection failure", 1690000740.0),
    ]
    groups, alerts = grouper.ingest(events)

    assert len(groups) == 1
    assert len(alerts) == 2
    assert any(a.code == "new_error_type" for a in alerts)
    assert any(a.code == "error_rate_spike" for a in alerts)
    assert groups[0].count == 6
    assert len(groups[0].source_ids) == 1


def test_grouper_build_dashboard_includes_trend_and_counts() -> None:
    grouper = ErrorGrouper(spike_window_seconds=300, spike_multiplier=1.5, spike_min_count=4, trend_bucket_seconds=60, trend_buckets=4)
    events = [
        _make_error("api", "database connection failure", 1690000350.0),
        _make_error("api", "database connection failure", 1690000400.0),
        _make_error("api", "database connection failure", 1690000650.0),
        _make_error("api", "database connection failure", 1690000680.0),
        _make_error("api", "database connection failure", 1690000710.0),
        _make_error("api", "database connection failure", 1690000740.0),
    ]
    grouper.ingest(events)

    payload = grouper.build_dashboard(as_of_ts=1690000740.0)
    assert len(payload["errors"]) == 1
    item = payload["errors"][0]
    assert item["count"] == 6
    assert "trend" in item
    assert item["trend"]["bucket_seconds"] == 60
    assert sum(item["trend"]["buckets"]) == 6
