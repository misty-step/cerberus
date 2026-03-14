"""Shared bootstrap helpers for review-run artifacts and contract assembly."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping

from . import github_platform as platform
from .review_run_contract import GitHubExecutionContext, ReviewRunContract, write_review_run_contract


def require_existing_file(path: Path, label: str) -> None:
    """Fail fast with the caller-facing bootstrap error wording."""

    if not path.is_file():
        raise FileNotFoundError(f"{label} file not found: {path}")


def fetch_pr_bootstrap(repo: str, pr_number: int) -> tuple[str, dict[str, object]]:
    """Fetch the diff and PR context needed to bootstrap a review run."""

    diff = platform.fetch_pr_diff(repo, pr_number)
    pr_context = platform.fetch_pr_context(repo, pr_number)
    return diff, pr_context


def write_pr_bootstrap_files(
    *,
    diff_file: Path,
    pr_context_file: Path,
    diff: str,
    pr_context: Mapping[str, object],
) -> None:
    """Persist bootstrap artifacts to disk."""

    diff_file.parent.mkdir(parents=True, exist_ok=True)
    pr_context_file.parent.mkdir(parents=True, exist_ok=True)
    diff_file.write_text(diff, encoding="utf-8")
    pr_context_file.write_text(json.dumps(pr_context), encoding="utf-8")


def read_pr_context_file(pr_context_file: Path) -> dict[str, object]:
    """Load and validate the bootstrap PR context payload."""

    try:
        payload = json.loads(pr_context_file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise OSError(f"unable to read PR context file {pr_context_file}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in PR context file {pr_context_file}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"invalid PR context file {pr_context_file}: expected object")

    return payload


def _branch_refs(pr_context: Mapping[str, object]) -> tuple[str, str]:
    head_ref = str(pr_context.get("headRefName") or "").strip()
    base_ref = str(pr_context.get("baseRefName") or "").strip()
    return head_ref, base_ref


def build_review_run(
    *,
    repo: str,
    pr_number: int,
    diff_file: Path,
    pr_context_file: Path,
    temp_dir: Path,
    token_env_var: str = "GH_TOKEN",
    workspace_root: str | None = None,
    pr_context: Mapping[str, object] | None = None,
) -> ReviewRunContract:
    """Build the provider-agnostic review-run contract from bootstrap artifacts."""

    payload = pr_context if pr_context is not None else read_pr_context_file(pr_context_file)
    head_ref, base_ref = _branch_refs(payload)
    resolved_workspace_root = workspace_root or os.getcwd()
    return ReviewRunContract(
        repository=repo,
        pr_number=pr_number,
        diff_file=str(diff_file),
        pr_context_file=str(pr_context_file),
        workspace_root=resolved_workspace_root,
        temp_dir=str(temp_dir),
        head_ref=head_ref,
        base_ref=base_ref,
        github=GitHubExecutionContext(repo=repo, pr_number=pr_number, token_env_var=token_env_var),
    )


def write_review_run_bootstrap(
    *,
    output: Path,
    repo: str,
    pr_number: int,
    diff_file: Path,
    pr_context_file: Path,
    token_env_var: str = "GH_TOKEN",
    workspace_root: str | None = None,
    pr_context: Mapping[str, object] | None = None,
) -> ReviewRunContract:
    """Write a review-run contract from already-fetched bootstrap artifacts."""

    contract = build_review_run(
        repo=repo,
        pr_number=pr_number,
        diff_file=diff_file,
        pr_context_file=pr_context_file,
        temp_dir=output.parent,
        token_env_var=token_env_var,
        workspace_root=workspace_root,
        pr_context=pr_context,
    )
    write_review_run_contract(output, contract)
    return contract
