"""Tests for quality report generation and aggregation."""
import importlib.util
import sys
from pathlib import Path

# Import aggregate-verdict.py via importlib (hyphen in filename prevents normal import)
_spec = importlib.util.spec_from_file_location(
    "aggregate_verdict",
    Path(__file__).resolve().parent.parent / "scripts" / "aggregate-verdict.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
_spec.loader.exec_module(_mod)

generate_quality_report = _mod.generate_quality_report

# Import quality-report.py
_qr_spec = importlib.util.spec_from_file_location(
    "quality_report",
    Path(__file__).resolve().parent.parent / "scripts" / "quality-report.py",
)
_qr_mod = importlib.util.module_from_spec(_qr_spec)
sys.modules[_qr_spec.name] = _qr_mod
_qr_spec.loader.exec_module(_qr_mod)

aggregate_reports = _qr_mod.aggregate_reports


def _sample_verdicts():
    return [
        {"reviewer": "APOLLO", "perspective": "correctness", "verdict": "PASS", "confidence": 0.85, "runtime_seconds": 45, "model_used": "kimi", "primary_model": "kimi", "fallback_used": False, "summary": "Looks good"},
        {"reviewer": "SENTINEL", "perspective": "security", "verdict": "SKIP", "confidence": 0, "runtime_seconds": 600, "model_used": "minimax", "primary_model": "minimax", "fallback_used": False, "summary": "timeout after 600s"},
        {"reviewer": "ATHENA", "perspective": "architecture", "verdict": "WARN", "confidence": 0.75, "runtime_seconds": 60, "model_used": "glm", "primary_model": "glm", "fallback_used": True, "summary": "Some issues"},
    ]


def _sample_council():
    return {"verdict": "WARN", "summary": "test"}


class TestQualityReportStructure:
    def test_report_has_required_sections(self):
        report = generate_quality_report(_sample_verdicts(), _sample_council(), [], "misty-step/test", "123", "abc123")
        assert "meta" in report
        assert "summary" in report
        assert "reviewers" in report
        assert "models" in report

    def test_meta_contains_repo(self):
        report = generate_quality_report(_sample_verdicts(), _sample_council(), [], "misty-step/test", "123", "abc123")
        assert report["meta"]["repo"] == "misty-step/test"
        assert report["meta"]["pr_number"] == "123"
        assert report["meta"]["head_sha"] == "abc123"
        assert isinstance(report["meta"]["generated_at"], float)


class TestQualityReportSummary:
    def test_total_reviewers(self):
        report = generate_quality_report(_sample_verdicts(), _sample_council(), [], "misty-step/test", "123", "abc123")
        assert report["summary"]["total_reviewers"] == 3

    def test_skip_count_and_rate(self):
        report = generate_quality_report(_sample_verdicts(), _sample_council(), [], "misty-step/test", "123", "abc123")
        assert report["summary"]["skip_count"] == 1
        assert report["summary"]["skip_rate"] == round(1 / 3, 4)

    def test_council_verdict(self):
        report = generate_quality_report(_sample_verdicts(), _sample_council(), [], "misty-step/test", "123", "abc123")
        assert report["summary"]["council_verdict"] == "WARN"

    def test_verdict_distribution(self):
        report = generate_quality_report(_sample_verdicts(), _sample_council(), [], "misty-step/test", "123", "abc123")
        dist = report["summary"]["verdict_distribution"]
        assert dist["PASS"] == 1
        assert dist["WARN"] == 1
        assert dist["SKIP"] == 1
        assert dist["FAIL"] == 0


class TestQualityReportModels:
    def test_model_aggregation(self):
        report = generate_quality_report(_sample_verdicts(), _sample_council(), [], "misty-step/test", "123", "abc123")
        assert "kimi" in report["models"]
        assert report["models"]["kimi"]["count"] == 1
        assert report["models"]["kimi"]["verdicts"]["PASS"] == 1

    def test_fallback_tracked(self):
        report = generate_quality_report(_sample_verdicts(), _sample_council(), [], "misty-step/test", "123", "abc123")
        assert report["models"]["glm"]["fallback_count"] == 1
        assert report["models"]["glm"]["fallback_rate"] > 0

    def test_runtime_stats(self):
        report = generate_quality_report(_sample_verdicts(), _sample_council(), [], "misty-step/test", "123", "abc123")
        assert report["models"]["kimi"]["avg_runtime_seconds"] == 45
        assert report["models"]["kimi"]["median_runtime_seconds"] == 45

    def test_runtime_count_in_model_stats(self):
        """runtime_count must be included so quality-report.py can aggregate correctly."""
        report = generate_quality_report(_sample_verdicts(), _sample_council(), [], "misty-step/test", "123", "abc123")
        assert report["models"]["kimi"]["runtime_count"] == 1
        # SENTINEL has runtime 600 (timeout) — still counted as runtime data
        assert report["models"]["minimax"]["runtime_count"] == 1


class TestQualityReportEdgeCases:
    def test_empty_verdicts(self):
        report = generate_quality_report([], {"verdict": "SKIP"}, [])
        assert report["summary"]["total_reviewers"] == 0
        assert "errors" in report

    def test_timed_out_field_set_correctly(self):
        """timed_out should be True for timeout-skip reviewers."""
        report = generate_quality_report(_sample_verdicts(), _sample_council(), [], "misty-step/test", "123", "abc123")
        reviewers = {r["reviewer"]: r for r in report["reviewers"]}
        # SENTINEL has SKIP + 600s runtime → timeout
        assert reviewers["SENTINEL"]["timed_out"] is True
        # APOLLO has PASS → not a timeout
        assert reviewers["APOLLO"]["timed_out"] is False

    def test_skipped_artifacts_included(self):
        skipped = [{"file": "bad.json", "reason": "invalid JSON"}]
        report = generate_quality_report(_sample_verdicts(), _sample_council(), skipped)
        assert "skipped_artifacts" in report
        assert len(report["skipped_artifacts"]) == 1

    def test_zero_runtime_recorded(self):
        """runtime_seconds=0 should be recorded, not dropped."""
        verdicts = [
            {"reviewer": "APOLLO", "perspective": "correctness", "verdict": "PASS",
             "confidence": 0.9, "runtime_seconds": 0, "model_used": "test-model",
             "summary": "fast"},
        ]
        report = generate_quality_report(verdicts, {"verdict": "PASS"}, [])
        assert report["models"]["test-model"]["avg_runtime_seconds"] == 0
        assert report["models"]["test-model"]["median_runtime_seconds"] == 0


# --- Tests for quality-report.py aggregate_reports ---

def _sample_quality_report(council_verdict="PASS", model="kimi", runtime=45, runtime_count=1):
    """Build a minimal quality report dict for testing aggregate_reports."""
    return {
        "meta": {"generated_at": 1700000000.0},
        "summary": {
            "total_reviewers": 3,
            "skip_count": 0,
            "parse_failure_count": 0,
            "council_verdict": council_verdict,
        },
        "models": {
            model: {
                "count": 1,
                "verdicts": {"PASS": 1, "WARN": 0, "FAIL": 0, "SKIP": 0},
                "total_runtime_seconds": runtime,
                "runtime_count": runtime_count,
                "fallback_count": 0,
                "parse_failures": 0,
            },
        },
    }


class TestAggregateReports:
    def test_empty_reports(self):
        result = aggregate_reports([])
        assert "error" in result

    def test_single_report(self):
        result = aggregate_reports([_sample_quality_report()])
        assert result["meta"]["total_runs_analyzed"] == 1
        assert len(result["model_rankings"]) == 1
        assert result["model_rankings"][0]["model"] == "kimi"
        assert result["model_rankings"][0]["success_rate"] == 1.0

    def test_council_verdict_distribution(self):
        reports = [
            _sample_quality_report(council_verdict="PASS"),
            _sample_quality_report(council_verdict="PASS"),
            _sample_quality_report(council_verdict="FAIL"),
        ]
        result = aggregate_reports(reports)
        dist = result["summary"]["council_verdict_distribution"]
        assert dist["PASS"] == 2
        assert dist["FAIL"] == 1

    def test_runtime_uses_runtime_count(self):
        """aggregate_reports should use runtime_count from model stats, not total count."""
        report = {
            "meta": {"generated_at": 1700000000.0},
            "summary": {"total_reviewers": 3, "skip_count": 1, "parse_failure_count": 0, "council_verdict": "PASS"},
            "models": {
                "test-model": {
                    "count": 3,
                    "verdicts": {"PASS": 2, "WARN": 0, "FAIL": 0, "SKIP": 1},
                    "total_runtime_seconds": 100,
                    "runtime_count": 2,  # only 2 of 3 reviews had runtime
                    "fallback_count": 0,
                    "parse_failures": 0,
                },
            },
        }
        result = aggregate_reports([report])
        # avg should be 100/2=50, not 100/3=33.3
        assert result["model_rankings"][0]["avg_runtime_seconds"] == 50.0

    def test_model_ranking_order(self):
        """Models ranked by success rate desc, then avg runtime asc."""
        reports = [
            _sample_quality_report(model="fast-good", runtime=10),
            _sample_quality_report(model="slow-good", runtime=100),
        ]
        result = aggregate_reports(reports)
        models = [m["model"] for m in result["model_rankings"]]
        # Same success rate, fast model ranks first
        assert models[0] == "fast-good"
        assert models[1] == "slow-good"

    def test_date_range(self):
        reports = [_sample_quality_report(), _sample_quality_report()]
        result = aggregate_reports(reports)
        assert result["meta"]["date_range"]["from"] is not None
        assert result["meta"]["date_range"]["to"] is not None
