#!/usr/bin/env python3
"""Enrich the quality report with OpenRouter account activity data.

Queries the OpenRouter management API for account credits and per-model
daily activity, then adds an ``account_activity`` section to the quality
report for budget visibility and cost reconciliation.

Usage:
    python3 scripts/openrouter-activity.py [--quality-report PATH] [--date YYYY-MM-DD]

Env:
    CERBERUS_OPENROUTER_MANAGEMENT_KEY  Required. OpenRouter management key
                                        (different from the reviewer API key).
    CERBERUS_TMP                        Temp dir containing quality-report.json
                                        (used when --quality-report is omitted).

The activity API returns completed-day data only. This script defaults to
querying yesterday (most recent completed UTC day). Pass --date to override.

Exit codes:
    0  Success (or graceful skip when key/report is absent).
    1  Fatal error (API failure, write failure).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
REQUEST_TIMEOUT = 30


def _get(path: str, key: str) -> dict:
    """GET from OpenRouter management API; return parsed JSON body."""
    url = f"{OPENROUTER_API_BASE}{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Request failed for {url}: {exc.reason}") from exc


def fetch_credits(key: str) -> dict:
    """Return raw credits response from /credits."""
    return _get("/credits", key)


def fetch_activity(key: str, activity_date: str) -> list[dict]:
    """Return activity rows for a given date (YYYY-MM-DD) from /activity."""
    data = _get(f"/activity?date={activity_date}", key)
    return data.get("data", [])


def build_activity_summary(rows: list[dict]) -> dict:
    """Aggregate per-row activity into totals and a per-model breakdown."""
    total_usage_usd = 0.0
    total_requests = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    per_model: dict[str, dict] = {}

    for row in rows:
        model = row.get("model") or row.get("model_permaslug") or "unknown"
        if model not in per_model:
            per_model[model] = {
                "usage_usd": 0.0,
                "requests": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
            }
        pm = per_model[model]
        usage = row.get("usage", 0) or 0
        pm["usage_usd"] += usage
        pm["requests"] += row.get("requests", 0) or 0
        pm["prompt_tokens"] += row.get("prompt_tokens", 0) or 0
        pm["completion_tokens"] += row.get("completion_tokens", 0) or 0
        total_usage_usd += usage
        total_requests += row.get("requests", 0) or 0
        total_prompt_tokens += row.get("prompt_tokens", 0) or 0
        total_completion_tokens += row.get("completion_tokens", 0) or 0

    for pm in per_model.values():
        pm["usage_usd"] = round(pm["usage_usd"], 8)

    return {
        "total_usage_usd": round(total_usage_usd, 8),
        "total_requests": total_requests,
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "per_model": per_model,
    }


def enrich_quality_report(report_path: Path, account_activity: dict) -> None:
    """Add account_activity section to an existing quality report JSON file."""
    try:
        report = json.loads(report_path.read_text())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON in {report_path}: {exc}") from exc
    except OSError as exc:
        raise RuntimeError(f"cannot read {report_path}: {exc}") from exc

    report["account_activity"] = account_activity

    try:
        report_path.write_text(json.dumps(report, indent=2))
    except OSError as exc:
        raise RuntimeError(f"cannot write {report_path}: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enrich quality report with OpenRouter account activity"
    )
    parser.add_argument(
        "--quality-report",
        type=Path,
        help="Path to quality-report.json (default: $CERBERUS_TMP/quality-report.json)",
    )
    parser.add_argument(
        "--date",
        help="Activity date to query (YYYY-MM-DD). Defaults to yesterday (most recent completed day).",
    )
    args = parser.parse_args()

    key = os.environ.get("CERBERUS_OPENROUTER_MANAGEMENT_KEY", "").strip()
    if not key:
        print(
            "openrouter-activity: CERBERUS_OPENROUTER_MANAGEMENT_KEY not set; skipping",
            file=sys.stderr,
        )
        return 0

    report_path = args.quality_report
    if not report_path:
        cerberus_tmp = os.environ.get("CERBERUS_TMP", "")
        if not cerberus_tmp:
            print(
                "openrouter-activity: --quality-report or CERBERUS_TMP required",
                file=sys.stderr,
            )
            return 1
        report_path = Path(cerberus_tmp) / "quality-report.json"

    if not report_path.exists():
        print(
            f"openrouter-activity: quality report not found at {report_path}; skipping",
            file=sys.stderr,
        )
        return 0

    # Default to yesterday — the most recent completed UTC day.
    activity_date = args.date or (date.today() - timedelta(days=1)).isoformat()

    try:
        credits_data = fetch_credits(key)
        activity_rows = fetch_activity(key, activity_date)
    except RuntimeError as exc:
        print(f"openrouter-activity: API error: {exc}", file=sys.stderr)
        return 1

    credits_payload = credits_data.get("data", credits_data)
    total_credits = credits_payload.get("total_credits")
    total_usage = credits_payload.get("total_usage")
    remaining: float | None = None
    if total_credits is not None and total_usage is not None:
        remaining = round(float(total_credits) - float(total_usage), 8)

    activity_summary = build_activity_summary(activity_rows)

    account_activity = {
        "fetched_at": time.time(),
        "credits": {
            "total_credits_usd": total_credits,
            "total_usage_usd": total_usage,
            "remaining_usd": remaining,
        },
        "activity_date": activity_date,
        "activity": activity_summary,
    }

    try:
        enrich_quality_report(report_path, account_activity)
    except RuntimeError as exc:
        print(f"openrouter-activity: {exc}", file=sys.stderr)
        return 1

    print(
        f"openrouter-activity: enriched quality report "
        f"(date={activity_date}, "
        f"total={activity_summary['total_usage_usd']:.4f} USD, "
        f"{len(activity_rows)} model entries)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
