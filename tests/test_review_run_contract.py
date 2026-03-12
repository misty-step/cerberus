import json
from pathlib import Path

import pytest

from lib.review_run_contract import (
    CONTRACT_VERSION,
    GitHubExecutionContext,
    ReviewRunContract,
    load_review_run_contract,
    load_review_run_contract_from_env,
    write_review_run_contract,
)


def test_write_and_load_review_run_contract_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "review-run.json"
    contract = ReviewRunContract(
        repository="misty-step/cerberus",
        pr_number=323,
        diff_file="/tmp/pr.diff",
        pr_context_file="/tmp/pr-context.json",
        workspace_root="/repo",
        temp_dir="/tmp/cerberus",
        github=GitHubExecutionContext(repo="misty-step/cerberus", pr_number=323),
    )

    write_review_run_contract(path, contract)

    assert load_review_run_contract(path) == contract


def test_load_review_run_contract_rejects_wrong_version(tmp_path: Path) -> None:
    path = tmp_path / "review-run.json"
    path.write_text(
        json.dumps(
            {
                "version": CONTRACT_VERSION + 1,
                "platform": "github",
                "repository": "misty-step/cerberus",
                "pr_number": 323,
                "diff_file": "/tmp/pr.diff",
                "pr_context_file": "/tmp/pr-context.json",
                "workspace_root": "/repo",
                "temp_dir": "/tmp/cerberus",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported review-run contract version"):
        load_review_run_contract(path)


def test_load_review_run_contract_from_env_loads_contract(tmp_path: Path) -> None:
    path = tmp_path / "review-run.json"
    contract = ReviewRunContract(
        repository="misty-step/cerberus",
        pr_number=323,
        diff_file="/tmp/pr.diff",
        pr_context_file="/tmp/pr-context.json",
        workspace_root="/repo",
        temp_dir="/tmp/cerberus",
        github=GitHubExecutionContext(repo="misty-step/cerberus", pr_number=323),
    )

    write_review_run_contract(path, contract)

    assert load_review_run_contract_from_env({"CERBERUS_REVIEW_RUN": str(path)}) == contract


def test_load_review_run_contract_rejects_non_object_github_context(tmp_path: Path) -> None:
    path = tmp_path / "review-run.json"
    path.write_text(
        json.dumps(
            {
                "version": CONTRACT_VERSION,
                "platform": "github",
                "repository": "misty-step/cerberus",
                "pr_number": 323,
                "diff_file": "/tmp/pr.diff",
                "pr_context_file": "/tmp/pr-context.json",
                "workspace_root": "/repo",
                "temp_dir": "/tmp/cerberus",
                "github": "bad",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="github must be an object"):
        load_review_run_contract(path)


def test_load_review_run_contract_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "review-run.json"
    path.write_text("{bad", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid JSON in review-run contract"):
        load_review_run_contract(path)


def test_load_review_run_contract_rejects_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"

    with pytest.raises(OSError, match="unable to read review-run contract"):
        load_review_run_contract(path)


def test_load_review_run_contract_from_env_returns_none_when_unset() -> None:
    assert load_review_run_contract_from_env({}) is None
