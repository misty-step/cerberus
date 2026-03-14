#!/usr/bin/env python3
"""Check Cerberus dogfood presence on core repos.

Reads defaults/dogfood.yml and queries GitHub for recent PRs on each
core repo. Reports presence classification per PR and flags repos
that fall below their minimum presence target.

Usage:
    python3 scripts/check-dogfood-presence.py [--window DAYS] [--json]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).parent.parent
DOGFOOD_CONFIG = ROOT / "defaults" / "dogfood.yml"


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load dogfood presence configuration."""
    path = config_path or DOGFOOD_CONFIG
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def classify_pr(
    *,
    cerberus_workflow_ran: bool,
    preflight_skipped: bool,
    reviewer_skips: int,
    total_reviewers: int,
) -> str:
    """Classify a PR into a presence bucket.

    Returns one of: absent, skipped, present_clean, present_with_skips.
    """
    if not cerberus_workflow_ran:
        return "absent"
    if preflight_skipped:
        return "skipped"
    if reviewer_skips > 0:
        return "present_with_skips"
    return "present_clean"


def _gh_json(args: list[str]) -> Any:  # pragma: no cover
    """Run a gh CLI command and parse JSON output."""
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def classify_pr_from_checks(pr: dict[str, Any]) -> str:
    """Classify a single PR dict (with statusCheckRollup) into a presence bucket."""
    checks = pr.get("statusCheckRollup", [])

    cerberus_checks = [
        c for c in checks
        if c.get("name", "").startswith("review / Cerberus")
    ]
    cerberus_ran = len(cerberus_checks) > 0

    preflight = [
        c for c in cerberus_checks
        if "preflight" in c.get("name", "")
    ]
    preflight_skipped = (
        len(preflight) > 0
        and all(c.get("conclusion") == "SKIPPED" for c in preflight)
    )

    reviewer_checks = [
        c for c in cerberus_checks
        if "wave" in c.get("name", "") and "gate" not in c.get("name", "")
    ]
    skips = sum(
        1 for c in reviewer_checks
        if c.get("conclusion") == "SKIPPED"
    )

    return classify_pr(
        cerberus_workflow_ran=cerberus_ran,
        preflight_skipped=preflight_skipped,
        reviewer_skips=skips,
        total_reviewers=len(reviewer_checks),
    )


def summarize_presence(repo: str, prs: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize Cerberus presence across a list of PR dicts.

    Pure function — no IO. Takes the repo name and a list of PR dicts
    with statusCheckRollup and returns classification summary.
    """
    classifications: dict[str, list[int]] = {
        "absent": [],
        "skipped": [],
        "present_clean": [],
        "present_with_skips": [],
    }

    for pr in prs:
        bucket = classify_pr_from_checks(pr)
        classifications[bucket].append(pr["number"])

    total = len(prs)
    present = len(classifications["present_clean"]) + len(classifications["present_with_skips"])
    presence_rate = present / total if total > 0 else 0.0

    return {
        "repo": repo,
        "total_prs": total,
        "presence_rate": round(presence_rate, 3),
        "classifications": {k: len(v) for k, v in classifications.items()},
        "pr_details": classifications,
    }


def check_repo_presence(  # pragma: no cover
    repo: str,
    window_days: int,
) -> dict[str, Any]:
    """Check Cerberus presence on recent PRs for a repo.

    Fetches PR data from GitHub and delegates to summarize_presence.
    """
    prs = _gh_json([
        "pr", "list",
        "--repo", repo,
        "--state", "all",
        "--limit", "50",
        "--json", "number,title,mergedAt,statusCheckRollup",
    ])
    return summarize_presence(repo, prs)


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Check Cerberus dogfood presence")
    parser.add_argument("--window", type=int, help="Override window days")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--config", type=Path, help="Override config path")
    args = parser.parse_args()

    config = load_config(args.config)
    window = args.window or config.get("window_days", 7)

    results = []
    below_target = []

    for entry in config["core_repos"]:
        repo = entry["repo"]
        min_presence = entry["min_presence"]

        try:
            result = check_repo_presence(repo, window)
            result["min_presence"] = min_presence
            result["meets_target"] = result["presence_rate"] >= min_presence
            results.append(result)

            if not result["meets_target"]:
                below_target.append(result)
        except Exception as e:
            results.append({
                "repo": repo,
                "error": str(e),
                "meets_target": False,
            })
            below_target.append(results[-1])

    if args.json:
        print(json.dumps({"results": results, "all_meet_target": len(below_target) == 0}, indent=2))
    else:
        for r in results:
            if "error" in r:
                print(f"  ERROR {r['repo']}: {r['error']}")
                continue
            status = "OK" if r["meets_target"] else "BELOW TARGET"
            print(
                f"  {status:>12}  {r['repo']:<35} "
                f"{r['presence_rate']:.0%} presence "
                f"(target: {r['min_presence']:.0%}, "
                f"{r['total_prs']} PRs)"
            )

        if below_target:
            print(f"\n{len(below_target)} repo(s) below presence target.")
            sys.exit(1)
        else:
            print("\nAll core repos meet presence targets.")


if __name__ == "__main__":
    main()
