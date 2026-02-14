"""Tests for generate_quality_report in aggregate-verdict.py."""
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


class TestQualityReportEdgeCases:
    def test_empty_verdicts(self):
        report = generate_quality_report([], {"verdict": "SKIP"}, [])
        assert report["summary"]["total_reviewers"] == 0
        assert "errors" in report

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
