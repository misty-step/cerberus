#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

from lib.markdown import details_block, location_link, repo_context, severity_icon


def render_findings(findings: list[dict], *, server: str, repo: str, sha: str) -> list[str]:
    lines: list[str] = []
    for f in findings:
        if not isinstance(f, dict):
            continue

        emoji = severity_icon(str(f.get("severity")))
        file = str(f.get("file", "unknown"))
        line = f.get("line")
        try:
            line = int(line)
        except (TypeError, ValueError):
            line = None
        if line is not None and line <= 0:
            line = None

        title = str(f.get("title", "Issue"))
        desc = str(f.get("description", "") or "")
        sugg = str(f.get("suggestion", "") or "")
        evidence = f.get("evidence", "")
        unverified = bool(f.get("_evidence_unverified"))
        reason = f.get("_evidence_reason", "")

        meta = ""
        if unverified:
            meta = f" _(unverified: {reason})_" if reason else " _(unverified)_"

        location = location_link(
            file,
            line,
            server=server,
            repo=repo,
            sha=sha,
            missing_label="unknown",
        )
        lines.append(f"- {emoji} {location} — {title}{meta}")

        details: list[str] = []
        if desc:
            details.extend(desc.splitlines())
        if sugg:
            details.extend(f"Suggestion: {sugg}".splitlines())
        if isinstance(evidence, str) and evidence.strip():
            details.append("Evidence:")
            details.append("```text")
            details.extend(evidence.strip().splitlines())
            details.append("```")

        lines.extend(details_block(details, summary="Details", indent="  "))

    return lines or ["- None"]


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render findings markdown from a verdict JSON file.")
    p.add_argument("--verdict-json", required=True, help="Path to verdict JSON file")
    p.add_argument("--output", required=True, help="Path to write findings markdown")
    p.add_argument("--server", default="", help="GitHub server URL (default: env GITHUB_SERVER_URL)")
    p.add_argument("--repo", default="", help="GitHub repo owner/name (default: env GITHUB_REPOSITORY)")
    p.add_argument("--sha", default="", help="Git SHA for blob links")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    verdict_path = Path(args.verdict_json)
    out_path = Path(args.output)

    try:
        data = json.loads(verdict_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"render-findings: failed to read or parse {verdict_path}: {exc}", file=sys.stderr)
        return 1

    if not isinstance(data, dict):
        print(f"render-findings: invalid verdict JSON in {verdict_path}: expected object", file=sys.stderr)
        return 1
    findings = data.get("findings", [])
    if not isinstance(findings, list):
        findings = []

    server, repo, sha = repo_context(server=args.server or None, repo=args.repo or None, sha=args.sha or None)

    try:
        out_path.write_text(
            "\n".join(render_findings(findings, server=server, repo=repo, sha=sha)),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"render-findings: failed to write {out_path}: {exc}", file=sys.stderr)
        return 1
    print(len(findings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
