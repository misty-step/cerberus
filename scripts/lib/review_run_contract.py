"""Provider-agnostic review execution contract."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

REVIEW_RUN_ENV_VAR = "CERBERUS_REVIEW_RUN"
CONTRACT_VERSION = 1


@dataclass(frozen=True)
class GitHubExecutionContext:
    """GitHub-specific execution context needed by runtime tools."""

    repo: str
    pr_number: int
    token_env_var: str = "GH_TOKEN"


@dataclass(frozen=True)
class ReviewRunContract:
    """Portable engine input for one Cerberus review run."""

    repository: str
    pr_number: int
    diff_file: str
    pr_context_file: str
    workspace_root: str
    temp_dir: str
    platform: str = "github"
    version: int = CONTRACT_VERSION
    github: GitHubExecutionContext | None = None


def _require_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid review-run contract: missing {key}")
    return value


def _require_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"invalid review-run contract: missing {key}")
    return value


def _load_github_context(payload: object) -> GitHubExecutionContext | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("invalid review-run contract: github must be an object")
    repo = _require_string(payload, "repo")
    pr_number = _require_int(payload, "pr_number")
    token_env_var = str(payload.get("token_env_var") or "GH_TOKEN").strip() or "GH_TOKEN"
    return GitHubExecutionContext(
        repo=repo,
        pr_number=pr_number,
        token_env_var=token_env_var,
    )


def load_review_run_contract(path: Path) -> ReviewRunContract:
    """Load and validate a review-run contract file."""

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OSError(f"unable to read review-run contract {path}: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in review-run contract {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"invalid review-run contract {path}: expected object")

    version = _require_int(payload, "version")
    if version != CONTRACT_VERSION:
        raise ValueError(
            f"unsupported review-run contract version {version} in {path}; "
            f"expected {CONTRACT_VERSION}"
        )

    return ReviewRunContract(
        version=version,
        platform=str(payload.get("platform") or "github").strip() or "github",
        repository=_require_string(payload, "repository"),
        pr_number=_require_int(payload, "pr_number"),
        diff_file=_require_string(payload, "diff_file"),
        pr_context_file=_require_string(payload, "pr_context_file"),
        workspace_root=_require_string(payload, "workspace_root"),
        temp_dir=_require_string(payload, "temp_dir"),
        github=_load_github_context(payload.get("github")),
    )


def write_review_run_contract(path: Path, contract: ReviewRunContract) -> None:
    """Write a review-run contract file."""

    payload = asdict(contract)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_review_run_contract_from_env(env: Mapping[str, str]) -> ReviewRunContract | None:
    """Load the configured review-run contract from env if present."""

    raw = str(env.get(REVIEW_RUN_ENV_VAR, "") or "").strip()
    if not raw:
        return None
    return load_review_run_contract(Path(raw))
