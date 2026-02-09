#!/usr/bin/env python3
import json
import os
import re
import sys
from pathlib import Path

# Prefix of the summary field in fallback verdicts produced by parse-review.py.
# parse-review.py appends ": <error detail>" after this prefix.
PARSE_FAILURE_PREFIX = "Review output could not be parsed"


def fail(msg: str, code: int = 2) -> None:
    print(f"aggregate-verdict: {msg}", file=sys.stderr)
    sys.exit(code)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path}: {exc}")
    except OSError as exc:
        fail(f"unable to read {path}: {exc}")


def parse_override(raw: str | None, head_sha: str | None) -> dict | None:
    if not raw or raw.strip() in {"", "null", "None"}:
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None

    # Keep backward compatibility with both normalized "actor" and legacy "author".
    actor = obj.get("actor") or obj.get("author") or "unknown"
    sha = obj.get("sha")
    reason = obj.get("reason")

    body = obj.get("body")
    if body:
        lines = [line.strip() for line in body.splitlines()]
        command_line = next((l for l in lines if l.startswith("/council override")), "")
        if command_line:
            match = re.search(r"sha=([0-9a-fA-F]+)", command_line)
            if match:
                sha = sha or match.group(1)
        for line in lines:
            if line.lower().startswith("reason:"):
                reason = reason or line.split(":", 1)[1].strip()
        if not reason:
            remainder = [l for l in lines if l and not l.startswith("/council override")]
            if remainder:
                reason = " ".join(remainder)

    if not sha or not reason:
        return None

    if len(sha) < 7:
        return None

    if head_sha:
        if not head_sha.startswith(sha):
            return None

    return {
        "actor": actor,
        "sha": sha,
        "reason": reason,
    }


POLICY_STRICTNESS = {
    "pr_author": 0,
    "write_access": 1,
    "maintainers_only": 2,
}


def validate_actor(
    actor: str,
    policy: str,
    pr_author: str | None,
    actor_permission: str | None = None,
) -> bool:
    if policy == "pr_author":
        return bool(pr_author) and actor.lower() == pr_author.lower()
    if policy == "write_access":
        return actor_permission in ("write", "maintain", "admin")
    if policy == "maintainers_only":
        return actor_permission in ("maintain", "admin")
    return False


def determine_effective_policy(
    verdicts: list[dict],
    reviewer_policies: dict[str, str],
    global_policy: str,
) -> str:
    """Pick the strictest override policy among failing reviewers."""
    failing = [v for v in verdicts if v.get("verdict") == "FAIL"]
    if not failing:
        return global_policy

    strictest = global_policy
    for v in failing:
        reviewer = v.get("reviewer", "")
        policy = reviewer_policies.get(reviewer, global_policy)
        if POLICY_STRICTNESS.get(policy, -1) > POLICY_STRICTNESS.get(strictest, -1):
            strictest = policy
    return strictest


def parse_expected_reviewers(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [name.strip() for name in raw.split(",") if name.strip()]


def is_fallback_verdict(verdict: dict) -> bool:
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
    if verdict.get("verdict") != "SKIP":
        return False
    summary = verdict.get("summary")
    if not isinstance(summary, str):
        return False
    return "timeout after" in summary.lower()


def has_critical_finding(verdict: dict) -> bool:
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


def aggregate(verdicts: list[dict], override: dict | None = None) -> dict:
    """Compute council verdict from individual reviewer verdicts.

    Returns the council dict with verdict, summary, reviewers, override, and stats.
    """
    override_used = override is not None

    fails = [v for v in verdicts if v["verdict"] == "FAIL"]
    warns = [v for v in verdicts if v["verdict"] == "WARN"]
    skips = [v for v in verdicts if v["verdict"] == "SKIP"]
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
        summary += f"Override by {override['actor']} for {override['sha']}."
    else:
        summary += f"Failures: {len(fails)}, warnings: {len(warns)}, skipped: {len(skips)}."
        if timed_out_reviewers:
            summary += f" Timed out reviewers: {', '.join(timed_out_reviewers)}."

    return {
        "verdict": council_verdict,
        "summary": summary,
        "reviewers": verdicts,
        "override": {
            "used": override_used,
            **(override or {}),
        },
        "stats": {
            "total": len(verdicts),
            "fail": len(fails),
            "warn": len(warns),
            "pass": len([v for v in verdicts if v["verdict"] == "PASS"]),
            "skip": len(skips),
        },
    }


def main() -> None:
    verdict_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("./verdicts")
    if not verdict_dir.exists():
        fail(f"verdict dir not found: {verdict_dir}")

    verdict_files = sorted(verdict_dir.glob("*.json"))
    if not verdict_files:
        fail("no verdict files found")

    verdicts = []
    for path in verdict_files:
        data = read_json(path)
        verdicts.append(
            {
                "reviewer": data.get("reviewer", path.stem),
                "perspective": data.get("perspective", path.stem),
                "verdict": data.get("verdict", "FAIL"),
                "confidence": data.get("confidence"),
                "summary": data.get("summary", ""),
                "findings": data.get("findings"),
                "stats": data.get("stats"),
                "runtime_seconds": data.get("runtime_seconds"),
            }
        )

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
    override = parse_override(os.environ.get("GH_OVERRIDE_COMMENT"), head_sha)
    if override:
        global_policy = os.environ.get("GH_OVERRIDE_POLICY", "pr_author")
        reviewer_policies_raw = os.environ.get("GH_REVIEWER_POLICIES")
        reviewer_policies: dict[str, str] = {}
        if reviewer_policies_raw:
            try:
                reviewer_policies = json.loads(reviewer_policies_raw)
            except json.JSONDecodeError:
                pass
        policy = determine_effective_policy(verdicts, reviewer_policies, global_policy)
        pr_author = os.environ.get("GH_PR_AUTHOR")
        actor_permission = os.environ.get("GH_OVERRIDE_ACTOR_PERMISSION")
        if not validate_actor(override["actor"], policy, pr_author, actor_permission):
            print(
                (
                    f"aggregate-verdict: warning: override actor '{override['actor']}' "
                    f"rejected by policy '{policy}'"
                ),
                file=sys.stderr,
            )
            override = None

    council = aggregate(verdicts, override)

    Path("/tmp/council-verdict.json").write_text(json.dumps(council, indent=2))

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
                f"- actor: {override['actor']}",
                f"- sha: {override['sha']}",
                f"- reason: {override['reason']}",
            ]
        )
    print("\n".join(lines))

    sys.exit(0)


if __name__ == "__main__":
    main()
