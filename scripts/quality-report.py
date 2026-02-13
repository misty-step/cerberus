#!/usr/bin/env python3
"""Aggregate Cerberus quality reports from multiple CI runs.

Usage:
    python3 scripts/quality-report.py --repo misty-step/moneta --last 20
    python3 scripts/quality-report.py --artifact-dir ./downloaded-artifacts/

Requires: gh CLI authenticated, or artifact JSON files locally.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def run_gh(args: list[str]) -> str:
    """Run gh CLI and return stdout."""
    result = subprocess.run(
        ["gh"] + args,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"gh error: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


def fetch_artifacts(repo: str, limit: int = 20) -> list[dict]:
    """Fetch quality report artifacts from recent workflow runs."""
    # Get recent successful workflow runs for the cerberus council
    runs_json = run_gh([
        "run", "list",
        "--repo", repo,
        "--workflow", "cerberus.yml",
        "--status", "success",
        "--limit", str(limit),
        "--json", "databaseId,headSha,event,number",
    ])
    runs = json.loads(runs_json)

    artifacts: list[dict] = []
    for run in runs:
        run_id = run["databaseId"]
        # List artifacts for this run
        try:
            artifacts_json = run_gh([
                "run", "view",
                "--repo", repo,
                str(run_id),
                "--json", "artifacts",
            ])
            run_data = json.loads(artifacts_json)
            for artifact in run_data.get("artifacts", []):
                if artifact.get("name") == "cerberus-quality-report":
                    artifacts.append({
                        "run_id": run_id,
                        "head_sha": run["headSha"],
                        "pr_number": run.get("number"),
                        "artifact_id": artifact["databaseId"],
                    })
        except SystemExit:
            continue

    return artifacts


def download_artifact(repo: str, artifact_id: int, output_dir: Path) -> Path | None:
    """Download an artifact to the specified directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        run_gh([
            "run", "download",
            "--repo", repo,
            str(artifact_id),
            "--dir", str(output_dir),
        ])
        # Find the downloaded quality-report.json
        report_path = output_dir / "quality-report.json"
        if report_path.exists():
            return report_path
    except SystemExit:
        pass
    return None


def load_quality_reports(artifact_dir: Path) -> list[dict]:
    """Load all quality-report.json files from a directory."""
    reports: list[dict] = []
    for report_path in artifact_dir.rglob("quality-report.json"):
        try:
            data = json.loads(report_path.read_text())
            reports.append(data)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Warning: could not load {report_path}: {exc}", file=sys.stderr)
    return reports


def aggregate_reports(reports: list[dict]) -> dict:
    """Aggregate multiple quality reports into summary statistics."""
    if not reports:
        return {"error": "No quality reports found"}

    total_runs = len(reports)
    total_reviewers = sum(r.get("summary", {}).get("total_reviewers", 0) for r in reports)
    total_skips = sum(r.get("summary", {}).get("skip_count", 0) for r in reports)
    total_parse_failures = sum(r.get("summary", {}).get("parse_failure_count", 0) for r in reports)

    # Council verdict distribution
    council_verdicts: dict[str, int] = {}
    for r in reports:
        v = r.get("summary", {}).get("council_verdict", "UNKNOWN")
        council_verdicts[v] = council_verdicts.get(v, 0) + 1

    # Per-model aggregation
    model_stats: dict[str, dict] = {}
    for r in reports:
        for model, stats in r.get("models", {}).items():
            if model not in model_stats:
                model_stats[model] = {
                    "total_count": 0,
                    "verdicts": {"PASS": 0, "WARN": 0, "FAIL": 0, "SKIP": 0},
                    "total_runtime_seconds": 0,
                    "runtime_count": 0,
                    "fallback_count": 0,
                    "parse_failures": 0,
                }
            ms = model_stats[model]
            count = stats.get("count", 0)
            ms["total_count"] += count
            for v in ["PASS", "WARN", "FAIL", "SKIP"]:
                ms["verdicts"][v] += stats.get("verdicts", {}).get(v, 0)
            ms["total_runtime_seconds"] += stats.get("total_runtime_seconds", 0)
            ms["runtime_count"] += count
            ms["fallback_count"] += stats.get("fallback_count", 0)
            ms["parse_failures"] += stats.get("parse_failures", 0)

    # Compute per-model averages and rankings
    model_summaries = []
    for model, stats in model_stats.items():
        count = stats["total_count"]
        if count == 0:
            continue
        avg_runtime = stats["total_runtime_seconds"] / stats["runtime_count"] if stats["runtime_count"] > 0 else 0
        skip_rate = stats["verdicts"]["SKIP"] / count
        parse_failure_rate = stats["parse_failures"] / count
        fallback_rate = stats["fallback_count"] / count
        success_rate = stats["verdicts"]["PASS"] / count

        model_summaries.append({
            "model": model,
            "total_runs": count,
            "avg_runtime_seconds": round(avg_runtime, 2),
            "skip_rate": round(skip_rate, 4),
            "parse_failure_rate": round(parse_failure_rate, 4),
            "fallback_rate": round(fallback_rate, 4),
            "success_rate": round(success_rate, 4),
            "verdict_distribution": stats["verdicts"],
        })

    # Rank models by success rate (descending), then by avg runtime (ascending)
    model_summaries.sort(key=lambda x: (-x["success_rate"], x["avg_runtime_seconds"]))

    return {
        "meta": {
            "total_runs_analyzed": total_runs,
            "date_range": {
                "from": reports[-1].get("meta", {}).get("generated_at") if reports else None,
                "to": reports[0].get("meta", {}).get("generated_at") if reports else None,
            },
        },
        "summary": {
            "total_reviewers": total_reviewers,
            "overall_skip_rate": round(total_skips / total_reviewers, 4) if total_reviewers > 0 else 0,
            "overall_parse_failure_rate": round(total_parse_failures / total_reviewers, 4) if total_reviewers > 0 else 0,
            "council_verdict_distribution": council_verdicts,
        },
        "model_rankings": model_summaries,
    }


def print_summary(summary: dict) -> None:
    """Print a human-readable summary."""
    print("\n" + "=" * 60)
    print("CERBERUS QUALITY REPORT SUMMARY")
    print("=" * 60)

    meta = summary.get("meta", {})
    print(f"\nRuns Analyzed: {meta.get('total_runs_analyzed', 0)}")

    s = summary.get("summary", {})
    print(f"Total Reviewers: {s.get('total_reviewers', 0)}")
    print(f"Overall SKIP Rate: {s.get('overall_skip_rate', 0):.2%}")
    print(f"Overall Parse Failure Rate: {s.get('overall_parse_failure_rate', 0):.2%}")

    print("\nCouncil Verdict Distribution:")
    for verdict, count in s.get("council_verdict_distribution", {}).items():
        print(f"  {verdict}: {count}")

    rankings = summary.get("model_rankings", [])
    if rankings:
        print("\nModel Rankings (by success rate):")
        print(f"{'Rank':<6}{'Model':<50}{'Success':<10}{'Skip':<10}{'Parse Fail':<12}{'Avg Runtime'}")
        print("-" * 100)
        for i, m in enumerate(rankings, 1):
            model_name = m["model"][:49]
            print(f"{i:<6}{model_name:<50}{m['success_rate']:<10.2%}{m['skip_rate']:<10.2%}{m['parse_failure_rate']:<12.2%}{m['avg_runtime_seconds']:.1f}s")

    print("\n" + "=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate Cerberus quality reports from CI runs"
    )
    parser.add_argument(
        "--repo",
        help="Repository in owner/name format (e.g., misty-step/moneta)",
    )
    parser.add_argument(
        "--last",
        type=int,
        default=20,
        help="Number of recent workflow runs to analyze (default: 20)",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        help="Directory containing downloaded quality-report.json files",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of human-readable summary",
    )

    args = parser.parse_args()

    reports: list[dict] = []

    if args.artifact_dir:
        # Load from local directory
        reports = load_quality_reports(args.artifact_dir)
    elif args.repo:
        # Fetch from GitHub
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            print(f"Fetching artifacts from {args.repo} (last {args.last} runs)...", file=sys.stderr)
            artifacts = fetch_artifacts(args.repo, args.last)
            print(f"Found {len(artifacts)} quality report artifacts", file=sys.stderr)

            for i, artifact in enumerate(artifacts, 1):
                print(f"Downloading artifact {i}/{len(artifacts)}...", file=sys.stderr)
                artifact_dir = tmp_path / f"run-{artifact['run_id']}"
                report_path = download_artifact(args.repo, artifact["artifact_id"], artifact_dir)
                if report_path:
                    try:
                        data = json.loads(report_path.read_text())
                        # Enrich with run metadata
                        data["_run_meta"] = {
                            "run_id": artifact["run_id"],
                            "head_sha": artifact["head_sha"],
                            "pr_number": artifact["pr_number"],
                        }
                        reports.append(data)
                    except (json.JSONDecodeError, OSError) as exc:
                        print(f"Warning: could not parse artifact: {exc}", file=sys.stderr)

            print(f"Successfully loaded {len(reports)} quality reports", file=sys.stderr)
    else:
        parser.error("Either --repo or --artifact-dir is required")

    if not reports:
        print("No quality reports found", file=sys.stderr)
        return 1

    summary = aggregate_reports(reports)

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print_summary(summary)

    return 0


if __name__ == "__main__":
    sys.exit(main())
