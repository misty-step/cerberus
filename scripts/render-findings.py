#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote


def blob_url(*, server: str, repo: str, sha: str, path: str, line: int | None) -> str | None:
    server = (server or "").rstrip("/")
    repo = (repo or "").strip()
    sha = (sha or "").strip()
    path = (path or "").strip()
    if not (server and repo and sha and path):
        return None
    url = f"{server}/{repo}/blob/{sha}/{quote(path, safe='/')}"
    if line is not None and line > 0:
        url += f"#L{line}"
    return url


def format_location(*, path: str, line: int | None, server: str, repo: str, sha: str) -> str:
    path = (path or "").strip()
    if not path:
        return "`unknown`"
    label = f"{path}:{line}" if line is not None and line > 0 else path
    url = blob_url(server=server, repo=repo, sha=sha, path=path, line=line)
    if not url:
        return f"`{label}`"
    return f"[`{label}`]({url})"


def render_findings(findings: list[dict], *, server: str, repo: str, sha: str) -> list[str]:
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

        location = format_location(path=file, line=line, server=server, repo=repo, sha=sha)
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

        if details:
            lines.extend([
                "  <details>",
                "  <summary>Details</summary>",
                "",
                *[f"  {ln}" if ln else "" for ln in details],
                "",
                "  </details>",
            ])

    return lines or ["- None"]


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render findings markdown from a verdict JSON file.")
    p.add_argument("--verdict-json", required=True, help="Path to verdict JSON file")
    p.add_argument("--output", required=True, help="Path to write findings markdown")
    p.add_argument("--server", default="", help="GitHub server URL (default: env GITHUB_SERVER_URL)")
    p.add_argument("--repo", default="", help="GitHub repo owner/name (default: env GITHUB_REPOSITORY)")
    p.add_argument("--sha", default="", help="Git SHA for blob links")
    return p.parse_args(argv)


def main() -> int:
    args = parse_args(sys.argv[1:])

    verdict_path = Path(args.verdict_json)
    out_path = Path(args.output)

    data = json.loads(verdict_path.read_text(encoding="utf-8"))
    findings = data.get("findings", [])
    if not isinstance(findings, list):
        findings = []

    server = args.server or ""
    repo = args.repo or ""
    if not server:
        server = os.environ.get("GITHUB_SERVER_URL", "")
    if not repo:
        repo = os.environ.get("GITHUB_REPOSITORY", "")

    out_path.write_text(
        "\n".join(render_findings(findings, server=server, repo=repo, sha=args.sha or "")),
        encoding="utf-8",
    )
    print(len(findings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
