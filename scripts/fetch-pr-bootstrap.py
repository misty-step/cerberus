#!/usr/bin/env python3
"""Fetch PR bootstrap artifacts through the shared GitHub platform adapter."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from lib import github_platform as platform


@dataclass(frozen=True)
class BootstrapResult:
    ok: bool
    error_kind: str
    error_message: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch PR bootstrap artifacts for Cerberus.")
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--pr", type=int, required=True, help="pull request number")
    parser.add_argument("--diff-file", required=True, help="Path to write the PR diff")
    parser.add_argument("--pr-context-file", required=True, help="Path to write the PR context JSON")
    parser.add_argument("--result-file", required=True, help="Path to write structured success/failure JSON")
    return parser.parse_args()


def write_result(path: Path, result: BootstrapResult) -> None:
    path.write_text(json.dumps(asdict(result)), encoding="utf-8")


def main() -> int:
    args = parse_args()
    diff_file = Path(args.diff_file)
    pr_context_file = Path(args.pr_context_file)
    result_file = Path(args.result_file)
    result_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        diff_file.parent.mkdir(parents=True, exist_ok=True)
        pr_context_file.parent.mkdir(parents=True, exist_ok=True)

        diff = platform.fetch_pr_diff(args.repo, args.pr)
        pr_context = platform.fetch_pr_context(args.repo, args.pr)

        diff_file.write_text(diff, encoding="utf-8")
        pr_context_file.write_text(json.dumps(pr_context), encoding="utf-8")
        result = BootstrapResult(ok=True, error_kind="", error_message="")
    except platform.GitHubAuthError as exc:
        result = BootstrapResult(ok=False, error_kind="auth", error_message=str(exc))
    except platform.GitHubPermissionError as exc:
        result = BootstrapResult(ok=False, error_kind="permissions", error_message=str(exc))
    except (platform.GitHubTimeoutError, platform.TransientGitHubError, ValueError, subprocess.CalledProcessError) as exc:
        result = BootstrapResult(ok=False, error_kind="other", error_message=str(exc))
    except OSError as exc:
        result = BootstrapResult(ok=False, error_kind="other", error_message=str(exc))

    write_result(result_file, result)
    if result.ok:
        return 0

    print(f"fetch-pr-bootstrap: {result.error_message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
