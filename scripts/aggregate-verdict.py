#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from lib.overrides import (
    Override,
    determine_effective_policy,
    parse_override,
    select_override,
    validate_actor,
)

# Prefix of the summary field in fallback verdicts produced by parse-review.py.
# parse-review.py appends ": <error detail>" after this prefix.
PARSE_FAILURE_PREFIX = "Review output could not be parsed"

# Maximum artifact file size in bytes (1 MB).
MAX_ARTIFACT_SIZE = 1_048_576

VALID_VERDICTS = {"PASS", "WARN", "FAIL", "SKIP"}
VALID_PARSE_FAILURE_POLICIES = {"fail", "warn", "skip"}
REQUIRED_ARTIFACT_FIELDS = ("verdict", "confidence", "summary")
CERBERUS_TMP = Path(os.environ.get("CERBERUS_TMP", tempfile.gettempdir()))


def fail(msg: str, code: int = 2) -> None:
    """Print an error message to stderr and exit with the given code."""
    print(f"aggregate-verdict: {msg}", file=sys.stderr)
    sys.exit(code)


def read_json(path: Path) -> dict:
    """Read and parse a JSON file, exiting with code 2 on error."""
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path}: {exc}")
    except OSError as exc:
        fail(f"unable to read {path}: {exc}")


def validate_artifact(path: Path) -> tuple[dict | None, str | None]:
    """Validate a verdict artifact file. Returns (data, None) on success or (None, error)."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        return None, f"unable to stat {path.name}: {exc}"

    if size > MAX_ARTIFACT_SIZE:
        return None, f"artifact size {size} exceeds limit {MAX_ARTIFACT_SIZE}"

    try:
        raw = path.read_text()
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"unable to read {path.name}: {exc}"

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON in {path.name}: {exc}"

    if not isinstance(data, dict):
        return None, f"{path.name}: root must be a JSON object"

    for field in REQUIRED_ARTIFACT_FIELDS:
        if field not in data:
            return None, f"{path.name}: missing required field '{field}'"

    if data["verdict"] not in VALID_VERDICTS:
        return None, f"{path.name}: invalid verdict '{data['verdict']}'"

    return data, None


def parse_expected_reviewers(raw: str | None) -> list[str]:
    """Parse a comma-separated list of expected reviewer names from an env var string."""
    if not raw:
        return []
    return [name.strip() for name in raw.split(",") if name.strip()]


def is_fallback_verdict(verdict: dict) -> bool:
    """Return True if the verdict was produced by parse-review.py's fallback path (parse failure)."""
    summary = verdict.get("summary")
    if not isinstance(summary, str):
        return False
    confidence = verdict.get("confidence")
    try:
        confidence_is_zero = float(confidence) == 0.0
    except (TypeError, ValueError):
        return False
    return confidence_is_zero and summary.startswith(PARSE_FAILURE_PREFIX)


def is_timeout_skip(verdict: dict) -> bool:
    """Return True if the SKIP verdict was caused by a reviewer timeout."""
    if verdict.get("verdict") != "SKIP":
        return False
    summary = verdict.get("summary")
    if not isinstance(summary, str):
        return False
    return "timeout after" in summary.lower()


def has_critical_finding(verdict: dict) -> bool:
    """Return True if the verdict contains at least one critical-severity finding."""
    stats = verdict.get("stats")
    if isinstance(stats, dict):
        critical = stats.get("critical")
        try:
            if int(critical) > 0:
                return True
        except (TypeError, ValueError):
            pass

    findings = verdict.get("findings")
    if isinstance(findings, list):
        for finding in findings:
            if isinstance(finding, dict) and finding.get("severity") == "critical":
                return True
    return False


def is_explicit_noncritical_fail(verdict: dict) -> bool:
    """Return True if the FAIL verdict has no critical findings and provides explicit evidence."""
    if verdict.get("verdict") != "FAIL":
        return False
    if has_critical_finding(verdict):
        return False

    stats = verdict.get("stats")
    if isinstance(stats, dict) and "critical" in stats:
        try:
            return int(stats.get("critical", 0)) == 0
        except (TypeError, ValueError):
            return False

    findings = verdict.get("findings")
    if isinstance(findings, list):
        return True

    # Missing evidence is treated as blocking for safety.
    return False


def aggregate(
    verdicts: list[dict],
    override: Override | None = None,
    parse_failure_policy: str = "warn",
) -> dict:
    """Compute council verdict from individual reviewer verdicts.

    Returns the council dict with verdict, summary, reviewers, override, and stats.

    *parse_failure_policy* controls how parse-failure verdicts (detected via
    ``is_fallback_verdict``) are treated during aggregation:

    - ``"fail"``: count as FAIL (legacy behaviour)
    - ``"warn"``: reclassify as SKIP for aggregation, emit warning (default)
    - ``"skip"``: reclassify as SKIP silently
    """
    override_used = override is not None

    # Determine effective verdict per reviewer — parse failures may be
    # reclassified so they don't block the council (#216).
    def _effective(v: dict) -> str:
        if is_fallback_verdict(v) and parse_failure_policy != "fail":
            return "SKIP"
        return v["verdict"]

    fails = [v for v in verdicts if _effective(v) == "FAIL"]
    warns = [v for v in verdicts if _effective(v) == "WARN"]
    skips = [v for v in verdicts if _effective(v) == "SKIP"]
    timed_out_reviewers = sorted(
        {
            str(v.get("reviewer") or v.get("perspective") or "unknown")
            for v in skips
            if is_timeout_skip(v)
        }
    )
    noncritical_fails = [v for v in fails if is_explicit_noncritical_fail(v)]
    blocking_fails = [v for v in fails if v not in noncritical_fails]

    # If ALL reviewers skipped, council verdict is SKIP (not FAIL)
    if len(skips) == len(verdicts) and len(verdicts) > 0:
        council_verdict = "SKIP"
    elif (blocking_fails or len(noncritical_fails) >= 2) and not override_used:
        council_verdict = "FAIL"
    elif warns or noncritical_fails:
        council_verdict = "WARN"
    else:
        council_verdict = "PASS"

    summary = f"{len(verdicts)} reviewers. "
    if override_used:
        summary += f"Override by {override.actor} for {override.sha}."
    else:
        summary += f"Failures: {len(fails)}, warnings: {len(warns)}, skipped: {len(skips)}."
        if timed_out_reviewers:
            summary += f" Timed out reviewers: {', '.join(timed_out_reviewers)}."

    parse_failures_reclassified = [
        v for v in verdicts
        if is_fallback_verdict(v) and parse_failure_policy != "fail"
    ]

    result = {
        "verdict": council_verdict,
        "summary": summary,
        "reviewers": verdicts,
        "override": {
            "used": override_used,
            **(asdict(override) if override else {}),
        },
        "stats": {
            "total": len(verdicts),
            "fail": len(fails),
            "warn": len(warns),
            "pass": len([v for v in verdicts if _effective(v) == "PASS"]),
            "skip": len(skips),
            "parse_failures_reclassified": len(parse_failures_reclassified),
        },
    }

    if parse_failures_reclassified and parse_failure_policy == "warn":
        reviewers = ", ".join(
            str(v.get("reviewer", "unknown")) for v in parse_failures_reclassified
        )
        print(
            f"aggregate-verdict: warning: {len(parse_failures_reclassified)} "
            f"parse-failure verdict(s) reclassified as SKIP: {reviewers}",
            file=sys.stderr,
        )

    return result


def generate_quality_report(
    verdicts: list[dict],
    council: dict,
    skipped_artifacts: list[dict],
    repo: str | None = None,
    pr_number: str | None = None,
    head_sha: str | None = None,
) -> dict:
    """Generate a quality report from council verdict data."""
    total = len(verdicts)
    if total == 0:
        return {
            "meta": {
                "repo": repo,
                "pr_number": pr_number,
                "head_sha": head_sha,
                "generated_at": time.time(),
            },
            "summary": {
                "total_reviewers": 0,
                "skip_rate": 0.0,
                "parse_failure_rate": 0.0,
                "council_verdict": council.get("verdict", "UNKNOWN"),
            },
            "reviewers": [],
            "models": {},
            "errors": ["No valid verdicts"],
        }

    skips = [v for v in verdicts if v["verdict"] == "SKIP"]
    fallback_verdicts = [v for v in verdicts if is_fallback_verdict(v)]
    skip_rate = len(skips) / total if total > 0 else 0.0
    parse_failure_rate = len(fallback_verdicts) / total if total > 0 else 0.0

    # Per-reviewer details
    reviewer_details = []
    for v in verdicts:
        detail = {
            "reviewer": v["reviewer"],
            "perspective": v["perspective"],
            "verdict": v["verdict"],
            "confidence": v.get("confidence"),
            "runtime_seconds": v.get("runtime_seconds"),
            "model_used": v.get("model_used"),
            "primary_model": v.get("primary_model"),
            "fallback_used": v.get("fallback_used", False),
            "parse_failed": is_fallback_verdict(v),
            "timed_out": is_timeout_skip(v),
        }
        reviewer_details.append(detail)

    # Per-model aggregation
    model_stats: dict[str, dict] = {}
    for v in verdicts:
        model = v.get("model_used") or v.get("primary_model") or "unknown"
        if model not in model_stats:
            model_stats[model] = {
                "count": 0,
                "verdicts": {"PASS": 0, "WARN": 0, "FAIL": 0, "SKIP": 0},
                "total_runtime_seconds": 0,
                "runtimes": [],
                "fallback_count": 0,
                "parse_failures": 0,
            }
        model_stats[model]["count"] += 1
        vd = v["verdict"]
        if vd in model_stats[model]["verdicts"]:
            model_stats[model]["verdicts"][vd] += 1
        if v.get("runtime_seconds") is not None:
            model_stats[model]["total_runtime_seconds"] += v["runtime_seconds"]
            model_stats[model]["runtimes"].append(v["runtime_seconds"])
        if v.get("fallback_used"):
            model_stats[model]["fallback_count"] += 1
        if is_fallback_verdict(v):
            model_stats[model]["parse_failures"] += 1

    # Compute averages and rates per model
    for model, stats in model_stats.items():
        count = stats["count"]
        runtimes = stats.pop("runtimes")
        runtime_count = len(runtimes)
        stats["runtime_count"] = runtime_count
        stats["avg_runtime_seconds"] = stats["total_runtime_seconds"] / runtime_count if runtime_count > 0 else 0
        stats["median_runtime_seconds"] = statistics.median(runtimes) if runtimes else 0
        stats["skip_rate"] = stats["verdicts"]["SKIP"] / count if count > 0 else 0
        stats["parse_failure_rate"] = stats["parse_failures"] / count if count > 0 else 0
        stats["fallback_rate"] = stats["fallback_count"] / count if count > 0 else 0

    # Verdict distribution
    verdict_distribution = {"PASS": 0, "WARN": 0, "FAIL": 0, "SKIP": 0}
    for v in verdicts:
        vd = v["verdict"]
        if vd in verdict_distribution:
            verdict_distribution[vd] += 1
        else:
            verdict_distribution[vd] = 1

    report = {
        "meta": {
            "repo": repo,
            "pr_number": pr_number,
            "head_sha": head_sha,
            "generated_at": time.time(),
        },
        "summary": {
            "total_reviewers": total,
            "skip_count": len(skips),
            "skip_rate": round(skip_rate, 4),
            "parse_failure_count": len(fallback_verdicts),
            "parse_failure_rate": round(parse_failure_rate, 4),
            "council_verdict": council.get("verdict", "UNKNOWN"),
            "verdict_distribution": verdict_distribution,
        },
        "reviewers": reviewer_details,
        "models": model_stats,
    }

    if skipped_artifacts:
        report["skipped_artifacts"] = skipped_artifacts

    return report


def main() -> None:
    """Aggregate reviewer verdict JSON files and write the council verdict to CERBERUS_TMP/council-verdict.json."""
    verdict_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("./verdicts")
    if not verdict_dir.exists():
        fail(f"verdict dir not found: {verdict_dir}")

    verdict_files = sorted(verdict_dir.glob("*.json"))
    if not verdict_files:
        fail("no verdict files found")

    verdicts = []
    skipped_artifacts: list[dict] = []
    for path in verdict_files:
        data, err = validate_artifact(path)
        if data is None:
            print(
                f"aggregate-verdict: warning: skipped {path.name}: {err}",
                file=sys.stderr,
            )
            skipped_artifacts.append({"file": path.name, "reason": err})
            continue
        entry = {
            "reviewer": data.get("reviewer", path.stem),
            "perspective": data.get("perspective", path.stem),
            "verdict": data.get("verdict", "FAIL"),
            "confidence": data.get("confidence"),
            "summary": data.get("summary", ""),
            "findings": data.get("findings"),
            "stats": data.get("stats"),
            "runtime_seconds": data.get("runtime_seconds"),
            "model_used": data.get("model_used"),
            "primary_model": data.get("primary_model"),
            "fallback_used": data.get("fallback_used"),
        }
        verdicts.append(entry)

    if not verdicts and skipped_artifacts:
        council = {
            "verdict": "SKIP",
            "summary": f"All {len(skipped_artifacts)} verdict artifact(s) were malformed and skipped.",
            "reviewers": [],
            "override": {"used": False},
            "stats": {
                "total": 0,
                "fail": 0,
                "warn": 0,
                "pass": 0,
                "skip": 0,
                "parse_failures_reclassified": 0,
            },
            "skipped_artifacts": skipped_artifacts,
        }
        _council_json = json.dumps(council, indent=2)
        _tmp = CERBERUS_TMP / "council-verdict.json.tmp"
        _tmp.write_text(_council_json)
        _tmp.rename(CERBERUS_TMP / "council-verdict.json")
        print(f"Council Verdict: SKIP\n\nAll artifacts skipped: {len(skipped_artifacts)} malformed.")
        sys.exit(0)

    expected_reviewers = parse_expected_reviewers(os.environ.get("EXPECTED_REVIEWERS"))
    fallback_reviewers = [v["reviewer"] for v in verdicts if is_fallback_verdict(v)]
    if expected_reviewers and len(verdict_files) != len(expected_reviewers):
        warning = (
            f"aggregate-verdict: warning: expected {len(expected_reviewers)} reviewers "
            f"({', '.join(expected_reviewers)}), got {len(verdict_files)} verdict files"
        )
        if fallback_reviewers:
            warning += f"; fallback verdicts: {', '.join(fallback_reviewers)}"
        print(warning, file=sys.stderr)
    elif fallback_reviewers:
        print(
            "aggregate-verdict: warning: fallback verdicts detected: "
            f"{', '.join(fallback_reviewers)}",
            file=sys.stderr,
        )

    head_sha = os.environ.get("GH_HEAD_SHA")
    global_policy = os.environ.get("GH_OVERRIDE_POLICY", "pr_author")
    reviewer_policies_raw = os.environ.get("GH_REVIEWER_POLICIES")
    reviewer_policies: dict[str, str] = {}
    if reviewer_policies_raw:
        try:
            parsed = json.loads(reviewer_policies_raw)
            if not isinstance(parsed, dict):
                raise ValueError("GH_REVIEWER_POLICIES must be a JSON object")
            reviewer_policies = parsed
        except (json.JSONDecodeError, ValueError) as exc:
            print(
                f"aggregate-verdict: warning: invalid GH_REVIEWER_POLICIES ({exc}); "
                "falling back to global policy",
                file=sys.stderr,
            )
    policy = determine_effective_policy(verdicts, reviewer_policies, global_policy)
    pr_author = os.environ.get("GH_PR_AUTHOR")

    # New multi-comment path: iterate comments chronologically, pick first authorized.
    comments_raw = os.environ.get("GH_OVERRIDE_COMMENTS")
    if comments_raw:
        actor_permissions_raw = os.environ.get("GH_OVERRIDE_ACTOR_PERMISSIONS")
        actor_permissions: dict[str, str] = {}
        if actor_permissions_raw:
            try:
                parsed_perms = json.loads(actor_permissions_raw)
                if not isinstance(parsed_perms, dict):
                    raise ValueError("GH_OVERRIDE_ACTOR_PERMISSIONS must be a JSON object")
                actor_permissions = parsed_perms
            except (json.JSONDecodeError, ValueError) as exc:
                print(
                    f"aggregate-verdict: warning: invalid GH_OVERRIDE_ACTOR_PERMISSIONS ({exc}); "
                    "treating all actors as unpermissioned",
                    file=sys.stderr,
                )
        override = select_override(
            comments_raw, head_sha, policy, pr_author, actor_permissions,
        )
    else:
        # Legacy single-comment path (backward compat).
        override = parse_override(os.environ.get("GH_OVERRIDE_COMMENT"), head_sha)
        if override:
            actor_permission = os.environ.get("GH_OVERRIDE_ACTOR_PERMISSION")
            if not validate_actor(override.actor, policy, pr_author, actor_permission):
                print(
                    (
                        f"aggregate-verdict: warning: override actor '{override.actor}' "
                        f"rejected by policy '{policy}'"
                    ),
                    file=sys.stderr,
                )
                override = None

    # Parse-failure policy: fail | warn | skip (default: warn)  (#216)
    parse_failure_policy = os.environ.get("PARSE_FAILURE_POLICY", "warn").lower()
    if parse_failure_policy not in VALID_PARSE_FAILURE_POLICIES:
        print(
            f"aggregate-verdict: warning: invalid PARSE_FAILURE_POLICY "
            f"'{parse_failure_policy}', defaulting to 'warn'",
            file=sys.stderr,
        )
        parse_failure_policy = "warn"

    council = aggregate(verdicts, override, parse_failure_policy=parse_failure_policy)

    if skipped_artifacts:
        council["skipped_artifacts"] = skipped_artifacts

    # Defensive guard: ensure .verdict is always present and valid (#213).
    if council.get("verdict") not in VALID_VERDICTS:
        council["verdict"] = "SKIP"
        council.setdefault(
            "summary", "Verdict missing or invalid after aggregation; defaulted to SKIP."
        )
        print(
            "aggregate-verdict: warning: council verdict was missing/invalid, "
            "defaulted to SKIP",
            file=sys.stderr,
        )

    council_json = json.dumps(council, indent=2)
    tmp_path = CERBERUS_TMP / "council-verdict.json.tmp"
    tmp_path.write_text(council_json)
    tmp_path.rename(CERBERUS_TMP / "council-verdict.json")

    # Generate quality report
    repo = os.environ.get("GITHUB_REPOSITORY")
    pr_number = os.environ.get("GH_PR_NUMBER")
    quality_report = generate_quality_report(
        verdicts, council, skipped_artifacts, repo, pr_number, head_sha
    )
    quality_report_path = CERBERUS_TMP / "quality-report.json"
    quality_report_path.write_text(json.dumps(quality_report, indent=2))
    print(f"aggregate-verdict: quality report written to {quality_report_path}", file=sys.stderr)

    council_verdict = council["verdict"]
    lines = [f"Council Verdict: {council_verdict}", ""]
    lines.append("Reviewers:")
    for v in verdicts:
        lines.append(f"- {v['reviewer']} ({v['perspective']}): {v['verdict']}")
    if override:
        lines.extend(
            [
                "",
                "Override:",
                f"- actor: {override.actor}",
                f"- sha: {override.sha}",
                f"- reason: {override.reason}",
            ]
        )
    print("\n".join(lines))

    sys.exit(0)


if __name__ == "__main__":
    main()
