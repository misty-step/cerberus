from __future__ import annotations

from pathlib import Path

import pytest

from lib.consumer_workflow_validator import validate_workflow_file


ROOT = Path(__file__).parent.parent


def _errors(findings):
    return [f for f in findings if f.level == "error"]


def test_minimal_template_has_no_errors():
    findings, _ = validate_workflow_file(ROOT / "templates/consumer-workflow-minimal.yml")
    assert _errors(findings) == []


def test_missing_verdict_write_permission_is_error(tmp_path: Path):
    wf = tmp_path / "cerberus.yml"
    wf.write_text(
        """
name: Cerberus
on: pull_request
jobs:
  review:
    permissions:
      contents: read
      pull-requests: read
    runs-on: ubuntu-latest
    steps:
      - uses: misty-step/cerberus@v2
        with:
          perspective: correctness
          github-token: ${{ secrets.GITHUB_TOKEN }}
          api-key: ${{ secrets.OPENROUTER_API_KEY }}
          post-comment: 'false'
  verdict:
    permissions:
      contents: read
      pull-requests: read
    runs-on: ubuntu-latest
    steps:
      - uses: misty-step/cerberus/verdict@v2
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
""".lstrip()
    )

    findings, _ = validate_workflow_file(wf)
    assert any("pull-requests: write" in f.message for f in _errors(findings))


def test_missing_github_token_is_error(tmp_path: Path):
    wf = tmp_path / "cerberus.yml"
    wf.write_text(
        """
name: Cerberus
on: pull_request
jobs:
  review:
    permissions:
      contents: read
      pull-requests: read
    runs-on: ubuntu-latest
    steps:
      - uses: misty-step/cerberus@v2
        with:
          perspective: correctness
          api-key: ${{ secrets.OPENROUTER_API_KEY }}
          post-comment: 'false'
""".lstrip()
    )

    findings, _ = validate_workflow_file(wf)
    assert any("with: github-token" in f.message for f in _errors(findings))


def test_post_comment_default_true_requires_pr_write(tmp_path: Path):
    wf = tmp_path / "cerberus.yml"
    wf.write_text(
        """
name: Cerberus
on: pull_request
jobs:
  review:
    permissions:
      contents: read
      pull-requests: read
    runs-on: ubuntu-latest
    steps:
      - uses: misty-step/cerberus@v2
        with:
          perspective: correctness
          github-token: ${{ secrets.GITHUB_TOKEN }}
          api-key: ${{ secrets.OPENROUTER_API_KEY }}
""".lstrip()
    )

    findings, _ = validate_workflow_file(wf)
    assert any("post-comment" in f.message and "pull-requests: write" in f.message for f in _errors(findings))


@pytest.mark.parametrize("bad_yaml", ["on: [pull_request\n", "jobs: [\n"])
def test_invalid_yaml_is_error(tmp_path: Path, bad_yaml: str):
    wf = tmp_path / "broken.yml"
    wf.write_text(bad_yaml)
    findings, _ = validate_workflow_file(wf)
    assert _errors(findings) != []

