"""Tests for quality report generation and aggregation."""
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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
        {
            "reviewer": "APOLLO", "perspective": "correctness", "verdict": "PASS",
            "confidence": 0.85, "runtime_seconds": 45, "model_used": "kimi",
            "primary_model": "kimi", "fallback_used": False, "summary": "Looks good",
        },
        {
            "reviewer": "SENTINEL", "perspective": "security", "verdict": "SKIP",
            "confidence": 0, "runtime_seconds": 600, "model_used": "minimax",
            "primary_model": "minimax", "fallback_used": False, "summary": "timeout after 600s",
        },
        {
            "reviewer": "ATHENA", "perspective": "architecture", "verdict": "WARN",
            "confidence": 0.75, "runtime_seconds": 60, "model_used": "glm",
            "primary_model": "glm", "fallback_used": True, "summary": "Some issues",
        },
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

    def test_skips_models_with_zero_count(self):
        report = {
            "meta": {"generated_at": 1700000000.0},
            "summary": {"total_reviewers": 2, "skip_count": 0, "parse_failure_count": 0, "council_verdict": "PASS"},
            "models": {
                "zero-model": {
                    "count": 0,
                    "verdicts": {"PASS": 0, "WARN": 0, "FAIL": 0, "SKIP": 0},
                    "total_runtime_seconds": 0,
                    "runtime_count": 0,
                    "fallback_count": 0,
                    "parse_failures": 0,
                },
                "active-model": {
                    "count": 1,
                    "verdicts": {"PASS": 1, "WARN": 0, "FAIL": 0, "SKIP": 0},
                    "total_runtime_seconds": 10,
                    "runtime_count": 1,
                    "fallback_count": 0,
                    "parse_failures": 0,
                },
            },
        }
        result = aggregate_reports([report])
        models = [m["model"] for m in result["model_rankings"]]
        assert "active-model" in models
        assert "zero-model" not in models


class TestRunGh:
    def test_run_gh_success(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="output", stderr="")
            result = _qr_mod.run_gh(["auth", "status"])

        assert result == "output"
        mock_run.assert_called_once_with(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=_qr_mod.GH_TIMEOUT_SECONDS,
        )

    def test_run_gh_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            with pytest.raises(_qr_mod.GHError, match="gh CLI not found"):
                _qr_mod.run_gh(["auth", "status"])

    def test_run_gh_nonzero(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="auth error")
            with pytest.raises(_qr_mod.GHError, match="auth error"):
                _qr_mod.run_gh(["auth", "status"])


class TestFetchArtifacts:
    def test_fetch_artifacts_filters_sorts_and_tolerates_failures(self, capsys):
        runs = [
            {"databaseId": 101, "headSha": "sha-101", "number": 11, "createdAt": "2024-01-01T00:00:00Z"},
            {"databaseId": 102, "headSha": "sha-102", "number": 12, "createdAt": "2024-01-03T00:00:00Z"},
            {"databaseId": 103, "headSha": "sha-103", "number": 13, "createdAt": "2024-01-02T00:00:00Z"},
            {"headSha": "broken", "number": 14, "createdAt": "2024-01-04T00:00:00Z"},
        ]

        def fake_run_gh(args):
            if args[:2] == ["run", "list"]:
                return json.dumps(runs)
            if args[:2] == ["run", "view"]:
                run_id = int(args[4])
                if run_id == 101:
                    return json.dumps({"artifacts": [{"name": _qr_mod.ARTIFACT_NAME, "databaseId": 501}]})
                if run_id == 102:
                    raise _qr_mod.GHError("run view failed")
                if run_id == 103:
                    return json.dumps({
                        "artifacts": [
                            {"name": "other-artifact", "databaseId": 999},
                            {"name": _qr_mod.ARTIFACT_NAME, "databaseId": 503},
                        ]
                    })
            raise AssertionError(f"Unexpected gh invocation: {args}")

        with patch.object(_qr_mod, "run_gh", side_effect=fake_run_gh):
            artifacts = _qr_mod.fetch_artifacts("misty-step/cerberus", limit=4)

        assert [a["run_id"] for a in artifacts] == [103, 101]
        assert [a["artifact_id"] for a in artifacts] == [503, 501]
        assert artifacts[0]["head_sha"] == "sha-103"
        assert "failed to fetch artifacts for run" in capsys.readouterr().err


class TestDownloadArtifact:
    def test_download_artifact_success(self, tmp_path):
        output_dir = tmp_path / "run-123"

        def fake_run_gh(_):
            (output_dir / "quality-report.json").write_text('{"summary": "ok"}')
            return ""

        with patch.object(_qr_mod, "run_gh", side_effect=fake_run_gh):
            run_id, report_path = _qr_mod.download_artifact("misty-step/cerberus", 123, output_dir)

        assert output_dir.exists()
        assert run_id == 123
        assert report_path == output_dir / "quality-report.json"
        assert report_path.exists()

    def test_download_artifact_gh_error_returns_none(self, tmp_path):
        with patch.object(_qr_mod, "run_gh", side_effect=_qr_mod.GHError("boom")):
            run_id, report_path = _qr_mod.download_artifact("misty-step/cerberus", 99, tmp_path / "run-99")

        assert run_id == 99
        assert report_path is None


class TestLoadQualityReports:
    def test_load_quality_reports_valid(self, tmp_path):
        report_path = tmp_path / "quality-report.json"
        report_path.write_text(json.dumps({"summary": "ok"}))

        result = _qr_mod.load_quality_reports(tmp_path)
        assert len(result) == 1
        assert result[0]["summary"] == "ok"

    def test_load_quality_reports_invalid_json(self, tmp_path, capsys):
        report_path = tmp_path / "quality-report.json"
        report_path.write_text("not json")

        result = _qr_mod.load_quality_reports(tmp_path)
        assert result == []
        assert "could not load" in capsys.readouterr().err


class TestPrintSummary:
    def test_print_summary_formatting(self, capsys):
        summary = {
            "meta": {"total_runs_analyzed": 2},
            "summary": {
                "total_reviewers": 6,
                "overall_skip_rate": 0.1667,
                "overall_parse_failure_rate": 0.0,
                "council_verdict_distribution": {"PASS": 1, "WARN": 1},
            },
            "model_rankings": [{
                "model": "kimi-k2.5",
                "success_rate": 0.9,
                "skip_rate": 0.1,
                "parse_failure_rate": 0.0,
                "avg_runtime_seconds": 12.3,
            }],
        }

        _qr_mod.print_summary(summary)
        out = capsys.readouterr().out
        assert "CERBERUS QUALITY REPORT SUMMARY" in out
        assert "Runs Analyzed: 2" in out
        assert "Overall SKIP Rate: 16.67%" in out
        assert "Council Verdict Distribution:" in out
        assert "Model Rankings (by success rate):" in out
        assert "kimi-k2.5" in out


class TestMain:
    def test_main_with_artifact_dir_and_json(self, tmp_path, capsys):
        report_path = tmp_path / "quality-report.json"
        report_path.write_text(json.dumps(_sample_quality_report()))

        with patch.object(sys, "argv", ["quality-report.py", "--artifact-dir", str(tmp_path), "--json"]):
            exit_code = _qr_mod.main()

        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["meta"]["total_runs_analyzed"] == 1

    def test_main_with_artifact_dir_no_reports(self, tmp_path, capsys):
        with patch.object(sys, "argv", ["quality-report.py", "--artifact-dir", str(tmp_path)]):
            exit_code = _qr_mod.main()

        assert exit_code == 1
        assert "No quality reports found" in capsys.readouterr().err

    def test_main_with_repo_without_gh(self, capsys):
        with (
            patch.object(sys, "argv", ["quality-report.py", "--repo", "misty-step/cerberus"]),
            patch.object(_qr_mod.shutil, "which", return_value=None),
        ):
            exit_code = _qr_mod.main()

        assert exit_code == 1
        assert "gh CLI not found" in capsys.readouterr().err

    def test_main_with_repo_happy_path_and_download_warnings(self, capsys):
        artifacts = [
            {"run_id": 1, "head_sha": "sha-1", "pr_number": 101},
            {"run_id": 2, "head_sha": "sha-2", "pr_number": 102},
            {"run_id": 3, "head_sha": "sha-3", "pr_number": 103},
        ]

        def fake_download_artifact(_, run_id, output_dir):
            if run_id == 1:
                output_dir.mkdir(parents=True, exist_ok=True)
                report_path = output_dir / "quality-report.json"
                report_path.write_text(json.dumps(_sample_quality_report(model="kimi")))
                return run_id, report_path
            if run_id == 2:
                output_dir.mkdir(parents=True, exist_ok=True)
                report_path = output_dir / "quality-report.json"
                report_path.write_text("not-json")
                return run_id, report_path
            raise RuntimeError("download failed")

        argv = ["quality-report.py", "--repo", "misty-step/cerberus", "--last", "3", "--json"]
        with (
            patch.object(sys, "argv", argv),
            patch.object(_qr_mod.shutil, "which", return_value="/usr/bin/gh"),
            patch.object(_qr_mod, "fetch_artifacts", return_value=artifacts),
            patch.object(_qr_mod, "download_artifact", side_effect=fake_download_artifact),
        ):
            exit_code = _qr_mod.main()

        assert exit_code == 0
        io = capsys.readouterr()
        payload = json.loads(io.out)
        assert payload["meta"]["total_runs_analyzed"] == 1
        assert "Found 3 quality report artifacts" in io.err
        assert "Successfully downloaded 1/3 quality reports" in io.err
        assert "Warning: could not parse artifact" in io.err
        assert "Warning: failed to download artifact" in io.err

    def test_main_requires_repo_or_artifact_dir(self):
        with patch.object(sys, "argv", ["quality-report.py"]):
            with pytest.raises(SystemExit) as exc:
                _qr_mod.main()
        assert exc.value.code == 2
