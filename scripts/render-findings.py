#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path


def render_findings(findings: list[dict]) -> list[str]:
    sev = {
        "critical": "🔴",
        "major": "🟠",
        "minor": "🟡",
        "info": "🔵",
    }

    lines: list[str] = []
    for f in findings:
        if not isinstance(f, dict):
            continue

        emoji = sev.get(f.get("severity", "info"), "🔵")
        file = f.get("file", "unknown")
        line = f.get("line", 0)
        title = f.get("title", "Issue")
        desc = f.get("description", "")
        sugg = f.get("suggestion", "")
        evidence = f.get("evidence", "")
        unverified = bool(f.get("_evidence_unverified"))
        reason = f.get("_evidence_reason", "")

        meta = ""
        if unverified:
            meta = f" _(unverified: {reason})_" if reason else " _(unverified)_"

        lines.append(f"- {emoji} `{file}:{line}` — {title}{meta}")
        if desc:
            lines.append(f"  {desc}")
        if sugg:
            lines.append(f"  Suggestion: {sugg}")
        if isinstance(evidence, str) and evidence.strip():
            lines.append("  Evidence:")
            lines.append("    ```text")
            for ln in evidence.strip().splitlines():
                lines.append(f"    {ln}")
            lines.append("    ```")

    return lines or ["- None"]


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render findings markdown from a verdict JSON file.")
    p.add_argument("--verdict-json", required=True, help="Path to verdict JSON file")
    p.add_argument("--output", required=True, help="Path to write findings markdown")
    return p.parse_args(argv)


def main() -> int:
    args = parse_args(sys.argv[1:])

    verdict_path = Path(args.verdict_json)
    out_path = Path(args.output)

    data = json.loads(verdict_path.read_text(encoding="utf-8"))
    findings = data.get("findings", [])
    if not isinstance(findings, list):
        findings = []

    out_path.write_text("\n".join(render_findings(findings)), encoding="utf-8")
    print(len(findings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

