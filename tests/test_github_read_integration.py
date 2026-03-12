"""Verify reviewer runtime includes read-only GitHub retrieval capabilities."""

from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
ACTION_FILE = ROOT / "action.yml"
REVIEWER_PROFILES_FILE = ROOT / "defaults" / "reviewer-profiles.yml"
GITHUB_READ_EXTENSION_FILE = ROOT / "pi" / "extensions" / "github-read.ts"


def test_github_read_extension_file_exists() -> None:
    assert GITHUB_READ_EXTENSION_FILE.exists(), "Expected github-read extension file to exist"


def test_reviewer_profiles_load_github_read_extension() -> None:
    data = yaml.safe_load(REVIEWER_PROFILES_FILE.read_text(encoding="utf-8"))
    base_extensions = data.get("base", {}).get("extensions", [])
    assert "pi/extensions/github-read.ts" in base_extensions


def test_run_review_env_uses_github_auth_and_review_run_contract() -> None:
    content = ACTION_FILE.read_text(encoding="utf-8")
    assert "GH_TOKEN: ${{ inputs.github-token }}" in content
    assert "CERBERUS_REVIEW_RUN: ${{ env.CERBERUS_TMP }}/review-run.json" in content
    assert "CERBERUS_LINKED_ISSUE_BODY_FILE" not in content
