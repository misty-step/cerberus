#!/usr/bin/env python3
"""Run a full Cerberus review lane outside GitHub Actions."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from lib.defaults_config import load_defaults_config
from lib.github_platform import fetch_pr_context, fetch_pr_diff
from lib.review_run_contract import GitHubExecutionContext, ReviewRunContract, write_review_run_contract


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTEXT_FIELDS = ["title", "author", "headRefName", "baseRefName", "body"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--pr", type=int, required=True, help="pull request number")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="directory for review-run inputs, reviewer artifacts, and verdict outputs",
    )
    parser.add_argument(
        "--reviewers",
        default="",
        help="comma-separated reviewer names to run (default: all reviewers in defaults/config.yml)",
    )
    parser.add_argument(
        "--token-env-var",
        default="GH_TOKEN",
        help="environment variable that carries GitHub auth into the isolated runtime",
    )
    return parser.parse_args()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def selected_reviewers(raw: str) -> list[str]:
    if raw.strip():
        return [item.strip() for item in raw.split(",") if item.strip()]
    cfg = load_defaults_config(ROOT / "defaults" / "config.yml")
    return [reviewer.name for reviewer in cfg.reviewers]


def build_review_run(
    *,
    repo: str,
    pr_number: int,
    diff_path: Path,
    pr_context_path: Path,
    output_dir: Path,
    token_env_var: str,
) -> ReviewRunContract:
    payload = json.loads(pr_context_path.read_text(encoding="utf-8"))
    head_ref = str(payload.get("headRefName") or "").strip()
    base_ref = str(payload.get("baseRefName") or "").strip()
    return ReviewRunContract(
        repository=repo,
        pr_number=pr_number,
        diff_file=str(diff_path),
        pr_context_file=str(pr_context_path),
        workspace_root=str(Path.cwd()),
        temp_dir=str(output_dir),
        head_ref=head_ref,
        base_ref=base_ref,
        github=GitHubExecutionContext(repo=repo, pr_number=pr_number, token_env_var=token_env_var),
    )


def run_command(args: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=str(ROOT), env=env, text=True, capture_output=True, check=False)


def load_json(path: Path) -> object:
    """Load JSON from disk. Callers are responsible for validating the shape."""

    return json.loads(path.read_text(encoding="utf-8"))


def enrich_verdict_metadata(*, output_dir: Path, perspective: str) -> None:
    verdict_path = output_dir / f"{perspective}-verdict.json"
    verdict = load_json(verdict_path)

    runtime_file = output_dir / f"{perspective}-runtime-seconds"
    if runtime_file.exists():
        runtime_text = runtime_file.read_text(encoding="utf-8").strip()
        if runtime_text.isdigit():
            verdict["runtime_seconds"] = int(runtime_text)

    model_used_file = output_dir / f"{perspective}-model-used"
    if model_used_file.exists():
        model_used = model_used_file.read_text(encoding="utf-8").strip()
        primary_model_file = output_dir / f"{perspective}-primary-model"
        configured_model_file = output_dir / f"{perspective}-configured-model"
        reviewer_desc_file = output_dir / f"{perspective}-reviewer-desc"

        primary_model = model_used
        if primary_model_file.exists():
            primary_model = primary_model_file.read_text(encoding="utf-8").strip() or model_used

        verdict["model_used"] = model_used
        verdict["primary_model"] = primary_model
        verdict["configured_model"] = (
            configured_model_file.read_text(encoding="utf-8").strip()
            if configured_model_file.exists()
            else ""
        )
        verdict["fallback_used"] = model_used != primary_model
        verdict["model_wave"] = os.environ.get("MODEL_WAVE", "")

        if reviewer_desc_file.exists():
            verdict["reviewer_description"] = reviewer_desc_file.read_text(encoding="utf-8").strip()

    write_json(verdict_path, verdict)


def run_reviewer(*, perspective: str, output_dir: Path, base_env: dict[str, str]) -> None:
    env = dict(base_env)
    env["PERSPECTIVE"] = perspective

    started_at = time.time()
    result = run_command(["bash", str(ROOT / "scripts" / "run-reviewer.sh"), perspective], env=env)
    runtime_seconds = int(time.time() - started_at)
    (output_dir / f"{perspective}-runtime-seconds").write_text(f"{runtime_seconds}\n", encoding="utf-8")

    if result.returncode != 0:
        raise RuntimeError(
            f"run-reviewer failed for {perspective} (exit {result.returncode})\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    parse_input = output_dir / f"{perspective}-output.txt"
    parse_input_override = output_dir / f"{perspective}-parse-input"
    if parse_input_override.exists():
        parse_input = Path(parse_input_override.read_text(encoding="utf-8").strip())

    parse_result = run_command(
        ["python3", str(ROOT / "scripts" / "parse-review.py"), str(parse_input)],
        env=env,
    )
    if parse_result.returncode != 0:
        raise RuntimeError(
            f"parse-review failed for {perspective} (exit {parse_result.returncode})\n"
            f"stdout:\n{parse_result.stdout}\n"
            f"stderr:\n{parse_result.stderr}"
        )

    (output_dir / f"{perspective}-verdict.json").write_text(parse_result.stdout, encoding="utf-8")
    enrich_verdict_metadata(output_dir=output_dir, perspective=perspective)


def aggregate_verdicts(
    *,
    output_dir: Path,
    repo: str,
    pr_number: int,
    reviewers: list[str],
    base_env: dict[str, str],
) -> None:
    verdict_dir = output_dir / "verdicts"
    verdict_dir.mkdir(parents=True, exist_ok=True)
    for stale_verdict in verdict_dir.glob("*.json"):
        stale_verdict.unlink()
    for reviewer in reviewers:
        source = output_dir / f"{reviewer}-verdict.json"
        target = verdict_dir / source.name
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    env = dict(base_env)
    env["CERBERUS_TMP"] = str(output_dir)
    env["GITHUB_REPOSITORY"] = repo
    env["GH_PR_NUMBER"] = str(pr_number)
    env["EXPECTED_REVIEWERS"] = ",".join(reviewers)

    result = run_command(
        ["python3", str(ROOT / "scripts" / "aggregate-verdict.py"), str(verdict_dir)],
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"aggregate-verdict failed (exit {result.returncode})\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    reviewers = selected_reviewers(args.reviewers)
    if not reviewers:
        print("non-gha-review-run: no reviewers selected", file=sys.stderr)
        return 2

    try:
        diff = fetch_pr_diff(args.repo, args.pr)
        pr_context = fetch_pr_context(args.repo, args.pr, fields=DEFAULT_CONTEXT_FIELDS)
    except Exception as exc:  # pragma: no cover - focused by unit tests through helpers
        print(f"non-gha-review-run: failed to fetch PR inputs: {exc}", file=sys.stderr)
        return 2

    diff_path = output_dir / "pr.diff"
    pr_context_path = output_dir / "pr-context.json"
    review_run_path = output_dir / "review-run.json"

    diff_path.write_text(diff, encoding="utf-8")
    write_json(pr_context_path, pr_context)
    write_review_run_contract(
        review_run_path,
        build_review_run(
            repo=args.repo,
            pr_number=args.pr,
            diff_path=diff_path,
            pr_context_path=pr_context_path,
            output_dir=output_dir,
            token_env_var=args.token_env_var,
        ),
    )

    base_env = dict(os.environ)
    base_env["CERBERUS_ROOT"] = str(ROOT)
    base_env["CERBERUS_TMP"] = str(output_dir)
    base_env["CERBERUS_REVIEW_RUN"] = str(review_run_path)

    try:
        for reviewer in reviewers:
            run_reviewer(perspective=reviewer, output_dir=output_dir, base_env=base_env)
        aggregate_verdicts(
            output_dir=output_dir,
            repo=args.repo,
            pr_number=args.pr,
            reviewers=reviewers,
            base_env=base_env,
        )
    except RuntimeError as exc:
        print(f"non-gha-review-run: {exc}", file=sys.stderr)
        return 1

    verdict_path = output_dir / "verdict.json"
    if not verdict_path.exists():
        print(
            f"non-gha-review-run: aggregate-verdict.py exited 0 but {verdict_path} was not written",
            file=sys.stderr,
        )
        return 1
    print(str(verdict_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
