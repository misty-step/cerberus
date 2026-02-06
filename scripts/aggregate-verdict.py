#!/usr/bin/env python3
import json
import os
import re
import sys
from pathlib import Path


def fail(msg: str, code: int = 2) -> None:
    print(f"aggregate-verdict: {msg}", file=sys.stderr)
    sys.exit(code)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path}: {exc}")


def parse_override(raw: str | None, head_sha: str | None) -> dict | None:
    if not raw or raw.strip() in {"", "null", "None"}:
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None

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

    if head_sha:
        if not (head_sha.startswith(sha) or sha.startswith(head_sha)):
            return None

    return {
        "actor": actor,
        "sha": sha,
        "reason": reason,
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
                "summary": data.get("summary", ""),
            }
        )

    head_sha = os.environ.get("GH_HEAD_SHA")
    override = parse_override(os.environ.get("GH_OVERRIDE_COMMENT"), head_sha)
    override_used = override is not None

    fails = [v for v in verdicts if v["verdict"] == "FAIL"]
    warns = [v for v in verdicts if v["verdict"] == "WARN"]

    if fails and not override_used:
        council_verdict = "FAIL"
    elif warns:
        council_verdict = "WARN"
    else:
        council_verdict = "PASS"

    summary = f"{len(verdicts)} reviewers. "
    if override_used:
        summary += f"Override by {override['actor']} for {override['sha']}."
    else:
        summary += f"Failures: {len(fails)}, warnings: {len(warns)}."

    council = {
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
        },
    }

    Path("/tmp/council-verdict.json").write_text(json.dumps(council, indent=2))

    lines = [f"Council Verdict: {council_verdict}", ""]
    lines.append("Reviewers:")
    for v in verdicts:
        lines.append(f"- {v['reviewer']} ({v['perspective']}): {v['verdict']}")
    if override_used:
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

    if council_verdict == "FAIL":
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
