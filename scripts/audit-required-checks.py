#!/usr/bin/env python3
"""Audit repo-level required status checks and print patch commands.

Usage:
    python3 scripts/audit-required-checks.py --org misty-step
    python3 scripts/audit-required-checks.py --org misty-step --match-check CI --replacement merge-gate
    python3 scripts/audit-required-checks.py --org misty-step --flag-ambiguous

Requires: gh CLI authenticated, jq available via gh --json output only.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass

GH_TIMEOUT_SECONDS = 30
AMBIGUOUS_CHECK_NAMES = frozenset({"CI", "check", "test", "build", "lint", "type-check", "Test"})


class GHError(Exception):
    """Raised when gh CLI returns a non-zero exit status."""


@dataclass(frozen=True)
class RepoProtection:
    """Repo default branch protection snapshot."""

    repo: str
    branch: str
    strict: bool
    checks: tuple[str, ...]
    has_app_scoped_checks: bool = False


@dataclass(frozen=True)
class RepoRef:
    """Repo inventory row from gh repo list."""

    repo: str
    branch: str
    archived: bool


def run_gh(args: list[str]) -> str:
    """Run gh and return stdout."""
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GHError("gh CLI not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise GHError(f"gh command timed out after {GH_TIMEOUT_SECONDS}s") from exc
    if result.returncode != 0:
        raise GHError((result.stderr or "").strip() or "gh command failed")
    return result.stdout


def load_json(args: list[str]) -> object:
    """Run gh and decode JSON output."""
    try:
        return json.loads(run_gh(args))
    except json.JSONDecodeError as exc:
        raise GHError(f"gh returned invalid JSON: {exc.msg}") from exc


def list_repos(org: str, limit: int, *, include_archived: bool) -> list[RepoRef]:
    """Return repo refs for org repos."""
    payload = load_json(
        [
            "repo",
            "list",
            org,
            "--limit",
            str(limit),
            "--json",
            "nameWithOwner,defaultBranchRef,isArchived",
        ]
    )
    if not isinstance(payload, list):
        raise GHError("gh repo list returned non-list JSON")
    repos: list[RepoRef] = []
    for item in payload:
        name = item.get("nameWithOwner")
        branch = (item.get("defaultBranchRef") or {}).get("name")
        archived = bool(item.get("isArchived", False))
        if not include_archived and archived:
            continue
        if isinstance(name, str) and isinstance(branch, str) and branch:
            repos.append(RepoRef(repo=name, branch=branch, archived=archived))
    return repos


def get_branch_protection(repo: str, branch: str) -> RepoProtection | None:
    """Return repo-level required checks for a protected branch, if any."""
    try:
        payload = load_json(["api", f"repos/{repo}/branches/{branch}/protection"])
    except GHError as exc:
        message = str(exc)
        if "404" in message or "Not Found" in message or "Branch not protected" in message:
            return None
        raise

    if not isinstance(payload, dict):
        raise GHError(f"{repo}: branch protection payload was not a JSON object")
    required = payload.get("required_status_checks") or {}
    if not isinstance(required, dict):
        raise GHError(f"{repo}: required_status_checks payload was not a JSON object")
    strict = bool(required.get("strict", False))
    names = []
    has_app_scoped_checks = False
    for context in required.get("contexts", []) or []:
        if isinstance(context, str) and context:
            names.append(context)
    for check in required.get("checks", []) or []:
        context = check.get("context") if isinstance(check, dict) else None
        app_id = check.get("app_id") if isinstance(check, dict) else None
        if isinstance(app_id, int) and app_id != -1:
            has_app_scoped_checks = True
        if isinstance(context, str) and context:
            names.append(context)
    deduped = tuple(sorted(set(names)))
    if not deduped:
        return None
    return RepoProtection(
        repo=repo,
        branch=branch,
        strict=strict,
        checks=deduped,
        has_app_scoped_checks=has_app_scoped_checks,
    )


def build_patch_payload(protection: RepoProtection, replacement: str, match_check: str) -> dict[str, object]:
    """Build required_status_checks payload with one renamed check."""
    updated = [replacement if check == match_check else check for check in protection.checks]
    return {
        "strict": protection.strict,
        "contexts": updated,
    }


def build_patch_command(protection: RepoProtection, replacement: str, match_check: str) -> str:
    """Build an exact gh api patch command for one repo."""
    payload = json.dumps(build_patch_payload(protection, replacement, match_check), separators=(",", ":"))
    command = (
        f"gh api -X PATCH repos/{protection.repo}/branches/{protection.branch}/protection/required_status_checks "
        f"--input - <<'JSON'\n{payload}\nJSON"
    )
    if protection.has_app_scoped_checks:
        return (
            "# warning: repo uses app-scoped required checks; review app bindings before applying\n"
            f"{command}"
        )
    return command


def positive_int(value: str) -> int:
    """Parse a positive integer CLI argument."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("--limit must be >= 1")
    return parsed


def format_markdown_report(
    protections: list[RepoProtection],
    *,
    match_check: str,
    replacement: str,
    flag_ambiguous: bool,
) -> str:
    """Render a compact markdown report."""
    repos_with_match = [p for p in protections if match_check in p.checks]
    repos_with_ambiguous = [
        p for p in protections if any(check in AMBIGUOUS_CHECK_NAMES for check in p.checks)
    ]
    lines = [
        "## Required Check Audit",
        f"- repos with repo-level required checks: {len(protections)}",
        f"- repos requiring `{match_check}`: {len(repos_with_match)}",
    ]
    if flag_ambiguous:
        lines.append(f"- repos with ambiguous check names: {len(repos_with_ambiguous)}")
    lines.extend(
        [
            "",
            "| Repo | Default Branch | Required Checks |",
            "|------|----------------|-----------------|",
        ]
    )
    for protection in protections:
        checks = ", ".join(protection.checks)
        lines.append(f"| `{protection.repo}` | `{protection.branch}` | `{checks}` |")
    if flag_ambiguous:
        lines.extend(["", "## Ambiguous Check Names"])
        if not repos_with_ambiguous:
            lines.append("- no repos use ambiguous required check names")
        else:
            for protection in repos_with_ambiguous:
                ambiguous = ", ".join(
                    check for check in protection.checks if check in AMBIGUOUS_CHECK_NAMES
                )
                lines.append(f"- `{protection.repo}`: {ambiguous}")
    lines.extend(
        [
            "",
            f"## Patch Plan: replace `{match_check}` with `{replacement}`",
        ]
    )
    if not repos_with_match:
        lines.append("- no repos require the legacy check")
        return "\n".join(lines)
    for protection in repos_with_match:
        lines.extend(
            [
                "",
                f"### `{protection.repo}`",
                "```bash",
                build_patch_command(protection, replacement, match_check),
                "```",
            ]
        )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    """Parse CLI args."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", required=True, help="GitHub organization name")
    parser.add_argument("--limit", type=positive_int, default=100, help="Max repos to inspect")
    parser.add_argument("--match-check", default="CI", help="Required check name to replace")
    parser.add_argument("--replacement", default="merge-gate", help="Replacement required check name")
    parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived repos in the audit output",
    )
    parser.add_argument(
        "--flag-ambiguous",
        action="store_true",
        help="Also report repos using ambiguous required check names like CI/test/build",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of markdown")
    return parser.parse_args()


def main() -> int:
    """Entry point."""
    args = parse_args()
    protections: list[RepoProtection] = []
    try:
        repos = list_repos(args.org, args.limit, include_archived=args.include_archived)
    except GHError as exc:
        print(f"error: failed to list repos for org '{args.org}': {exc}", file=sys.stderr)
        return 1
    for repo in repos:
        try:
            protection = get_branch_protection(repo.repo, repo.branch)
        except GHError as exc:
            print(f"warning: skipping {repo.repo}: {exc}", file=sys.stderr)
            continue
        if protection is not None:
            protections.append(protection)
    protections.sort(key=lambda item: item.repo)

    if args.json:
        payload = {
            "org": args.org,
            "repos_with_required_checks": len(protections),
            "repos_requiring_match_check": len([p for p in protections if args.match_check in p.checks]),
            "repos_with_ambiguous_checks": len(
                [p for p in protections if any(check in AMBIGUOUS_CHECK_NAMES for check in p.checks)]
            ),
            "protections": [
                {
                    "repo": p.repo,
                    "branch": p.branch,
                    "strict": p.strict,
                    "checks": list(p.checks),
                    "ambiguous_checks": [
                        check for check in p.checks if check in AMBIGUOUS_CHECK_NAMES
                    ],
                    "patch_command": build_patch_command(p, args.replacement, args.match_check)
                    if args.match_check in p.checks
                    else None,
                }
                for p in protections
            ],
        }
        print(json.dumps(payload, indent=2))
        return 0

    print(
        format_markdown_report(
            protections,
            match_check=args.match_check,
            replacement=args.replacement,
            flag_ambiguous=args.flag_ambiguous,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
