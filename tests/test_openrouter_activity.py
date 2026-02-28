"""Tests for scripts/openrouter-activity.py"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest.mock as mock
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Load the module under test
# ---------------------------------------------------------------------------
_SCRIPT = Path(__file__).parent.parent / "scripts" / "openrouter-activity.py"
_spec = importlib.util.spec_from_file_location("openrouter_activity", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

build_activity_summary = _mod.build_activity_summary
enrich_quality_report = _mod.enrich_quality_report
fetch_credits = _mod.fetch_credits
fetch_activity = _mod.fetch_activity


# ---------------------------------------------------------------------------
# Unit tests: build_activity_summary
# ---------------------------------------------------------------------------
class TestBuildActivitySummary:
    def test_empty_rows(self):
        result = build_activity_summary([])
        assert result["total_usage_usd"] == 0.0
        assert result["total_requests"] == 0
        assert result["total_prompt_tokens"] == 0
        assert result["total_completion_tokens"] == 0
        assert result["per_model"] == {}

    def test_single_row(self):
        rows = [{
            "model": "google/gemini-3-flash-preview",
            "usage": 14.63,
            "requests": 2199,
            "prompt_tokens": 1_000_000,
            "completion_tokens": 200_000,
        }]
        result = build_activity_summary(rows)
        assert result["total_usage_usd"] == pytest.approx(14.63)
        assert result["total_requests"] == 2199
        assert result["total_prompt_tokens"] == 1_000_000
        assert result["total_completion_tokens"] == 200_000
        assert "google/gemini-3-flash-preview" in result["per_model"]

    def test_multiple_rows_same_model_are_aggregated(self):
        rows = [
            {"model": "moonshotai/kimi-k2.5", "usage": 10.0, "requests": 100, "prompt_tokens": 500, "completion_tokens": 50},
            {"model": "moonshotai/kimi-k2.5", "usage": 5.0,  "requests": 50,  "prompt_tokens": 250, "completion_tokens": 25},
        ]
        result = build_activity_summary(rows)
        pm = result["per_model"]["moonshotai/kimi-k2.5"]
        assert pm["usage_usd"] == pytest.approx(15.0)
        assert pm["requests"] == 150
        assert pm["prompt_tokens"] == 750
        assert pm["completion_tokens"] == 75

    def test_multiple_rows_different_models(self):
        rows = [
            {"model": "model-a", "usage": 1.0, "requests": 10, "prompt_tokens": 100, "completion_tokens": 10},
            {"model": "model-b", "usage": 2.0, "requests": 20, "prompt_tokens": 200, "completion_tokens": 20},
        ]
        result = build_activity_summary(rows)
        assert result["total_usage_usd"] == pytest.approx(3.0)
        assert len(result["per_model"]) == 2

    def test_falls_back_to_model_permaslug_when_model_absent(self):
        rows = [{"model_permaslug": "some/model", "usage": 1.0, "requests": 5, "prompt_tokens": 10, "completion_tokens": 2}]
        result = build_activity_summary(rows)
        assert "some/model" in result["per_model"]

    def test_unknown_model_label_when_both_absent(self):
        rows = [{"usage": 1.0, "requests": 1, "prompt_tokens": 10, "completion_tokens": 5}]
        result = build_activity_summary(rows)
        assert "unknown" in result["per_model"]

    def test_none_values_treated_as_zero(self):
        rows = [{"model": "x", "usage": None, "requests": None, "prompt_tokens": None, "completion_tokens": None}]
        result = build_activity_summary(rows)
        assert result["total_usage_usd"] == 0.0
        assert result["total_requests"] == 0


# ---------------------------------------------------------------------------
# Unit tests: enrich_quality_report
# ---------------------------------------------------------------------------
class TestEnrichQualityReport:
    def test_adds_account_activity_section(self, tmp_path):
        report_path = tmp_path / "quality-report.json"
        report_path.write_text(json.dumps({"summary": {"total_cost_usd": 0.001}}))
        activity = {"fetched_at": 1234567890, "credits": {}, "activity_date": "2026-02-27", "activity": {}}
        enrich_quality_report(report_path, activity)
        result = json.loads(report_path.read_text())
        assert "account_activity" in result
        assert result["account_activity"]["activity_date"] == "2026-02-27"

    def test_preserves_existing_report_fields(self, tmp_path):
        report_path = tmp_path / "quality-report.json"
        report_path.write_text(json.dumps({"summary": {"total_cost_usd": 0.001}, "reviewers": []}))
        enrich_quality_report(report_path, {"fetched_at": 0, "credits": {}, "activity_date": "x", "activity": {}})
        result = json.loads(report_path.read_text())
        assert result["summary"]["total_cost_usd"] == pytest.approx(0.001)
        assert result["reviewers"] == []

    def test_raises_on_missing_file(self, tmp_path):
        with pytest.raises(RuntimeError, match="cannot read"):
            enrich_quality_report(tmp_path / "nonexistent.json", {})

    def test_raises_on_invalid_json(self, tmp_path):
        bad_path = tmp_path / "quality-report.json"
        bad_path.write_text("not json{{{")
        with pytest.raises(RuntimeError, match="invalid JSON"):
            enrich_quality_report(bad_path, {})


# ---------------------------------------------------------------------------
# Integration tests: main() via subprocess
# ---------------------------------------------------------------------------
import os
import subprocess


def _run_script(args: list[str], env_extra: dict | None = None) -> tuple[int, str, str]:
    env = os.environ.copy()
    env.pop("CERBERUS_OPENROUTER_MANAGEMENT_KEY", None)
    env.pop("CERBERUS_TMP", None)
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


class TestMainNoKey:
    def test_exits_0_with_warning_when_key_absent(self, tmp_path):
        code, _, err = _run_script([])
        assert code == 0
        assert "not set" in err

    def test_skips_gracefully_without_report(self, tmp_path):
        code, _, err = _run_script([], env_extra={"CERBERUS_OPENROUTER_MANAGEMENT_KEY": ""})
        assert code == 0


class TestMainMissingReport:
    def test_exits_0_when_report_not_found(self, tmp_path):
        code, _, err = _run_script(
            ["--quality-report", str(tmp_path / "missing.json")],
            env_extra={"CERBERUS_OPENROUTER_MANAGEMENT_KEY": "sk-fake-key"},
        )
        assert code == 0
        assert "not found" in err

    def test_exits_1_when_cerberus_tmp_set_but_report_absent(self, tmp_path):
        # CERBERUS_TMP set but quality-report.json doesn't exist → graceful skip
        code, _, err = _run_script(
            [],
            env_extra={
                "CERBERUS_OPENROUTER_MANAGEMENT_KEY": "sk-fake-key",
                "CERBERUS_TMP": str(tmp_path),
            },
        )
        assert code == 0
        assert "not found" in err


class TestMainApiError:
    def test_exits_1_on_api_http_error(self, tmp_path):
        report_path = tmp_path / "quality-report.json"
        report_path.write_text(json.dumps({"summary": {}}))

        with mock.patch.object(_mod, "_get", side_effect=RuntimeError("HTTP 401: Unauthorized")), \
             mock.patch.dict(os.environ, {"CERBERUS_OPENROUTER_MANAGEMENT_KEY": "sk-fake", "CERBERUS_TMP": str(tmp_path)}, clear=False), \
             mock.patch("sys.argv", ["openrouter-activity.py"]):
            code = _mod.main()
        assert code == 1


class TestMainSuccess:
    """Test happy-path using mocked API calls."""

    def _make_report(self, tmp_path: Path) -> Path:
        p = tmp_path / "quality-report.json"
        p.write_text(json.dumps({
            "summary": {"total_cost_usd": 0.00123},
            "reviewers": [],
        }))
        return p

    def _call_main(self, tmp_path):
        """Helper: call main() with sys.argv neutralized."""
        with mock.patch("sys.argv", ["openrouter-activity.py"]), \
             mock.patch.dict(os.environ, {"CERBERUS_OPENROUTER_MANAGEMENT_KEY": "sk-fake", "CERBERUS_TMP": str(tmp_path)}, clear=False):
            return _mod.main()

    def test_enriches_report_with_account_activity(self, tmp_path):
        report_path = self._make_report(tmp_path)
        credits_response = {"data": {"total_credits": 2850.0, "total_usage": 2780.32}}
        activity_rows = [
            {"model": "google/gemini-3-flash-preview", "usage": 14.63, "requests": 2199, "prompt_tokens": 1_000_000, "completion_tokens": 200_000},
            {"model": "moonshotai/kimi-k2.5", "usage": 10.0, "requests": 500, "prompt_tokens": 500_000, "completion_tokens": 100_000},
        ]

        def fake_get(path: str, key: str) -> dict:
            if "/credits" in path:
                return credits_response
            if "/activity" in path:
                return {"data": activity_rows}
            raise AssertionError(f"unexpected path: {path}")

        with mock.patch.object(_mod, "_get", side_effect=fake_get):
            code = self._call_main(tmp_path)

        assert code == 0
        result = json.loads(report_path.read_text())
        assert "account_activity" in result
        aa = result["account_activity"]
        assert aa["credits"]["total_credits_usd"] == pytest.approx(2850.0)
        assert aa["credits"]["remaining_usd"] == pytest.approx(2850.0 - 2780.32)
        assert "activity_date" in aa
        assert "activity" in aa
        assert "google/gemini-3-flash-preview" in aa["activity"]["per_model"]

    def test_existing_report_fields_preserved(self, tmp_path):
        self._make_report(tmp_path)

        def fake_get(path: str, key: str) -> dict:
            if "/credits" in path:
                return {"data": {"total_credits": 100.0, "total_usage": 50.0}}
            return {"data": []}

        with mock.patch.object(_mod, "_get", side_effect=fake_get):
            self._call_main(tmp_path)

        result = json.loads((tmp_path / "quality-report.json").read_text())
        assert result["summary"]["total_cost_usd"] == pytest.approx(0.00123)
        assert result["reviewers"] == []

    def test_remaining_usd_computed_correctly(self, tmp_path):
        self._make_report(tmp_path)

        def fake_get(path: str, key: str) -> dict:
            if "/credits" in path:
                return {"data": {"total_credits": 1000.0, "total_usage": 123.456}}
            return {"data": []}

        with mock.patch.object(_mod, "_get", side_effect=fake_get):
            self._call_main(tmp_path)

        result = json.loads((tmp_path / "quality-report.json").read_text())
        remaining = result["account_activity"]["credits"]["remaining_usd"]
        assert remaining == pytest.approx(1000.0 - 123.456, rel=1e-6)

    def test_none_credits_fields_produce_none_remaining(self, tmp_path):
        self._make_report(tmp_path)

        def fake_get(path: str, key: str) -> dict:
            if "/credits" in path:
                return {"data": {"total_credits": None, "total_usage": None}}
            return {"data": []}

        with mock.patch.object(_mod, "_get", side_effect=fake_get):
            self._call_main(tmp_path)

        result = json.loads((tmp_path / "quality-report.json").read_text())
        assert result["account_activity"]["credits"]["remaining_usd"] is None
