from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from pkg.errortracking.config import ErrorSourceConfig
from pkg.errortracking.grouper import ErrorAlert, ErrorGrouper
from pkg.errortracking.parser import LogParser, ParsedError, _normalize_signature


def test_error_tracking_config_defaults_work_when_fields_missing() -> None:
    from pkg.errortracking.config import ErrorTrackingConfig

    cfg = ErrorTrackingConfig.from_dict({})
    assert cfg.spike_window_seconds == 3600
    assert cfg.spike_multiplier == 2.5
    assert cfg.spike_min_count == 5
    assert cfg.trend_bucket_seconds == 300
    assert cfg.trend_buckets == 12


def _make_error(source: str, signature: str, ts: float, message: str = "Database error") -> ParsedError:
    return ParsedError(
        error_key=f"{source}:{signature}",
        signature=signature,
        message=message,
        source_id=source,
        seen_at=ts,
        seen_at_iso=datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
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
                "baseDir": str(tmp_path),
                "format": "plain",
                "errorPatterns": ["ERROR", "CRITICAL"],
            }
        )
    )
    parsed = parser.parse()

    assert len(parsed) == 2
    assert parsed[0].source_id == "api"
    assert parsed[0].signature != parsed[1].signature


def test_log_parser_plain_uses_embedded_timestamp_when_present(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    log.write_text("2026-02-18T10:11:12Z ERROR worker crashed\n")

    parser = LogParser(
        ErrorSourceConfig.from_dict(
            {
                "id": "api",
                "path": str(log),
                "baseDir": str(tmp_path),
                "format": "plain",
                "errorPatterns": ["ERROR"],
            }
        )
    )
    parsed = parser.parse()

    assert len(parsed) == 1
    assert parsed[0].seen_at_iso.startswith("2026-02-18T10:11:12")
    assert parsed[0].message == "ERROR worker crashed"


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
                "baseDir": str(tmp_path),
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


def test_error_source_config_rejects_path_outside_base_dir(tmp_path: Path) -> None:
    outside = Path("/tmp/forbidden.log")
    with pytest.raises(ValueError, match="within baseDir"):
        ErrorSourceConfig.from_dict(
            {
                "id": "api",
                "path": str(outside),
                "baseDir": str(tmp_path),
                "format": "plain",
                "errorPatterns": ["ERROR"],
            }
        )


def test_error_source_config_rejects_non_string_format(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    log.write_text("ERROR crash")

    with pytest.raises(ValueError, match="format must be one of"):
        ErrorSourceConfig.from_dict(
            {
                "id": "api",
                "path": str(log),
                "baseDir": str(tmp_path),
                "format": 123,
                "errorPatterns": ["ERROR"],
            }
        )


def test_error_source_config_accepts_file_alias(tmp_path: Path) -> None:
    log = tmp_path / "alias.log"
    log.write_text("ERROR boom")

    config = ErrorSourceConfig.from_dict(
        {
            "id": "api",
            "file": "alias.log",
            "baseDir": str(tmp_path),
            "format": "plain",
            "errorPatterns": ["ERROR"],
        }
    )
    assert config.log_file == str(log.resolve())


def test_log_parser_returns_empty_for_missing_file(tmp_path: Path) -> None:
    parser = LogParser(
        ErrorSourceConfig.from_dict(
            {
                "id": "api",
                "path": "missing.log",
                "baseDir": str(tmp_path),
                "format": "plain",
                "errorPatterns": ["ERROR"],
            }
        )
    )
    assert parser.parse() == []


def test_log_parser_skips_invalid_json_line(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    log.write_text("not-json\n{\"message\":\"DatabaseError: boom\"}")
    parser = LogParser(
        ErrorSourceConfig.from_dict(
            {
                "id": "worker",
                "path": str(log),
                "baseDir": str(tmp_path),
                "format": "json",
                "errorPatterns": ["DatabaseError"],
            }
        )
    )
    parsed = parser.parse()
    assert len(parsed) == 1
    assert parsed[0].message == "DatabaseError: boom"


def test_log_parser_respects_poll_lines_limit(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    log.write_text("\n".join(f"ERROR line {idx}" for idx in range(10)))

    parser = LogParser(
        ErrorSourceConfig.from_dict(
            {
                "id": "api",
                "path": str(log),
                "baseDir": str(tmp_path),
                "format": "plain",
                "pollLines": 2,
                "errorPatterns": ["ERROR"],
            }
        )
    )

    parsed = parser.parse()
    assert [item.message for item in parsed] == ["ERROR line 8", "ERROR line 9"]


def test_log_parser_handles_permission_error_from_tail_reader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "app.log"
    log.write_text("ERROR denied\n")

    def _raise_permission_error(_path: str, _max_lines: int) -> list[str]:
        raise PermissionError("denied")

    monkeypatch.setattr("pkg.errortracking.parser._tail_lines", _raise_permission_error)
    parser = LogParser(
        ErrorSourceConfig.from_dict(
            {
                "id": "api",
                "path": str(log),
                "baseDir": str(tmp_path),
                "format": "plain",
                "errorPatterns": ["ERROR"],
            }
        )
    )
    assert parser.parse() == []


def test_log_parser_parses_space_separated_json_timestamp(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    log.write_text('{"timestamp":"2026-02-18 10:11:12","message":"DatabaseError: boom"}\n')
    parser = LogParser(
        ErrorSourceConfig.from_dict(
            {
                "id": "worker",
                "path": str(log),
                "baseDir": str(tmp_path),
                "format": "json",
                "errorPatterns": ["DatabaseError"],
            }
        )
    )
    parsed = parser.parse()
    assert len(parsed) == 1
    assert parsed[0].seen_at_iso.startswith("2026-02-18T10:11:12")


def test_normalize_signature_masks_ids_and_numbers() -> None:
    normalized = _normalize_signature("DB failure user=42 request=0xABCD1234 trace deadbeefcafebabe")
    assert normalized == "db failure user=<num> request=0x<id> trace <id>"


def test_error_source_config_rejects_bool_poll_lines_and_empty_patterns(tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    log.write_text("ERROR boom")

    with pytest.raises(ValueError, match="pollLines must be an integer"):
        ErrorSourceConfig.from_dict(
            {
                "id": "api",
                "path": str(log),
                "baseDir": str(tmp_path),
                "format": "plain",
                "pollLines": True,
                "errorPatterns": ["ERROR"],
            }
        )

    with pytest.raises(ValueError, match="errorPatterns cannot be empty"):
        ErrorSourceConfig.from_dict(
            {
                "id": "api",
                "path": str(log),
                "baseDir": str(tmp_path),
                "format": "plain",
                "errorPatterns": [],
            }
        )


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


def test_error_grouper_handles_out_of_order_timestamps_and_eviction() -> None:
    grouper = ErrorGrouper(spike_window_seconds=300, spike_multiplier=2.0, spike_min_count=4, trend_bucket_seconds=60, trend_buckets=4)
    old = [
        _make_error("api", "stale", 100.0),
        _make_error("api", "stale", 200.0),
    ]
    grouper.ingest(old)
    fresh = [
        _make_error("api", "fresh", 1000.0),
        _make_error("api", "fresh", 800.0),
        _make_error("api", "fresh", 900.0),
    ]
    groups, _alerts = grouper.ingest(fresh)

    by_key = {group.error_key: group for group in groups}
    assert "api:stale" not in by_key
    assert "api:fresh" in by_key
    assert by_key["api:fresh"].first_seen.startswith("1970-01-01T00:13:20")
    assert by_key["api:fresh"].last_seen.startswith("1970-01-01T00:16:40")


def test_error_grouper_records_sink_failures() -> None:
    grouper = ErrorGrouper(spike_window_seconds=300, spike_multiplier=1.5, spike_min_count=4, trend_bucket_seconds=60, trend_buckets=4)

    class FailingSink:
        def send(self, _alert: ErrorAlert) -> None:
            raise RuntimeError("sink exploded")

    _groups, alerts = grouper.ingest([_make_error("api", "database connection failure", 1000.0)], sinks=[FailingSink()])
    assert any(alert.code == "new_error_type" for alert in alerts)
    assert any("RuntimeError: sink exploded" in value for value in grouper.sink_errors)


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
    assert sum(item["trend"]["buckets"]) == 4
    assert item["trend"]["current_window_count"] + item["trend"]["previous_window_count"] == 6
