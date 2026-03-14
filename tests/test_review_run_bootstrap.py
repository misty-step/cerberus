"""Tests for shared review-run bootstrap helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path

from scripts.lib import review_run_bootstrap as mod


def test_fetch_pr_bootstrap_delegates_to_platform(monkeypatch) -> None:
    seen: list[tuple[str, str, int]] = []

    def fake_fetch_pr_diff(repo: str, pr_number: int) -> str:
        seen.append(("diff", repo, pr_number))
        return "diff --git a/app.py b/app.py\n"

    def fake_fetch_pr_context(repo: str, pr_number: int) -> dict[str, object]:
        seen.append(("context", repo, pr_number))
        return {"title": "PR", "headRefName": "feature", "baseRefName": "master"}

    monkeypatch.setattr(mod.platform, "fetch_pr_diff", fake_fetch_pr_diff)
    monkeypatch.setattr(mod.platform, "fetch_pr_context", fake_fetch_pr_context)

    diff, pr_context = mod.fetch_pr_bootstrap("misty-step/cerberus", 326)

    assert diff == "diff --git a/app.py b/app.py\n"
    assert pr_context["headRefName"] == "feature"
    assert seen == [
        ("diff", "misty-step/cerberus", 326),
        ("context", "misty-step/cerberus", 326),
    ]


def test_write_review_run_bootstrap_uses_existing_pr_context_file(monkeypatch, tmp_path: Path) -> None:
    diff_file = tmp_path / "pr.diff"
    pr_context_file = tmp_path / "pr-context.json"
    output = tmp_path / "review-run.json"
    diff_file.write_text("diff --git a/app.py b/app.py\n", encoding="utf-8")
    pr_context_file.write_text(
        json.dumps({"title": "PR", "headRefName": "feature/run", "baseRefName": "master"}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    contract = mod.write_review_run_bootstrap(
        output=output,
        repo="misty-step/cerberus",
        pr_number=323,
        diff_file=diff_file,
        pr_context_file=pr_context_file,
        token_env_var="CERBERUS_TOKEN",
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["repository"] == "misty-step/cerberus"
    assert payload["pr_number"] == 323
    assert payload["head_ref"] == "feature/run"
    assert payload["base_ref"] == "master"
    assert payload["workspace_root"] == os.getcwd()
    assert payload["temp_dir"] == str(tmp_path)
    assert payload["github"] == {
        "repo": "misty-step/cerberus",
        "pr_number": 323,
        "token_env_var": "CERBERUS_TOKEN",
    }
    assert contract.head_ref == "feature/run"


def test_write_pr_bootstrap_files_creates_parent_directories(tmp_path: Path) -> None:
    diff_file = tmp_path / "nested" / "pr.diff"
    pr_context_file = tmp_path / "nested" / "pr-context.json"

    mod.write_pr_bootstrap_files(
        diff_file=diff_file,
        pr_context_file=pr_context_file,
        diff="diff --git a/app.py b/app.py\n",
        pr_context={"title": "PR", "headRefName": "feature", "baseRefName": "master"},
    )

    assert diff_file.read_text(encoding="utf-8") == "diff --git a/app.py b/app.py\n"
    assert json.loads(pr_context_file.read_text(encoding="utf-8"))["baseRefName"] == "master"
